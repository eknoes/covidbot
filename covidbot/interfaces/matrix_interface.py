import asyncio
import logging
import os
from typing import List, Union, Optional

import aiofiles
import prometheus_async
from PIL import Image
from nio import AsyncClient, AsyncClientConfig, RoomMessageText, MatrixRoom, MegolmEvent, \
    InviteMemberEvent, RoomMemberEvent, RoomKeyRequestResponse, \
    JoinError, RoomKeyRequestError, UploadResponse, ErrorResponse, ProfileSetAvatarError, \
    ProfileSetDisplayNameError, RoomLeaveResponse
from nio.store import SqliteStore

from covidbot.bot import Bot
from covidbot.interfaces.bot_response import BotResponse
from covidbot.interfaces.messenger_interface import MessengerInterface
from covidbot.metrics import RECV_MESSAGE_COUNT, SENT_MESSAGE_COUNT, FAILED_MESSAGE_COUNT, \
    BOT_RESPONSE_TIME, SENT_IMAGES_COUNT
from covidbot.utils import adapt_text


class MatrixInterface(MessengerInterface):
    display_name: str
    avatar_path: str

    identifier: str
    username: str

    matrix: AsyncClient
    bot: Bot

    log = logging.getLogger(__name__)

    public_url: str
    web_dir: str
    debug: bool

    def __init__(self, bot: Bot, home_server: str, username: str, access_token: str,
                 device_id: str, store_filepath: str, web_dir: str, public_url: str,
                 display_name: str, avatar_path: str, debug: bool = False):

        if not os.path.exists(store_filepath):
            os.makedirs(store_filepath)

        self.debug = debug
        self.public_url = public_url
        self.web_dir = web_dir

        self.display_name = display_name
        self.avatar_path = avatar_path

        self.username = username
        self.identifier = f"@{username}:{home_server[home_server.find('//') + 2:]}"

        self.matrix = AsyncClient(home_server, self.identifier, device_id,
                                  store_path=store_filepath,
                                  config=AsyncClientConfig(encryption_enabled=True,
                                                           store=SqliteStore,
                                                           store_name="matrix.db",
                                                           store_sync_tokens=True))
        self.matrix.access_token = access_token
        self.matrix.user_id = self.identifier

        self.matrix.add_event_callback(self.handle_message, RoomMessageText)
        self.matrix.add_event_callback(self.crypto_event, MegolmEvent)
        self.matrix.add_event_callback(self.invite_event, InviteMemberEvent)
        self.matrix.add_event_callback(self.room_event, RoomMemberEvent)

        self.matrix.restore_login(self.identifier, device_id, access_token)
        self.bot = bot

        self.log.level = logging.DEBUG
        self.log.debug(f"Initialized Matrix Bot: {self.identifier}")

    async def crypto_event(self, room: MatrixRoom, event: MegolmEvent):
        self.log.error(f"Can't decrypt for {room.name}")
        if event.session_id not in self.matrix.outgoing_key_requests:
            self.log.warning(f"Fetching keys for {room.name}")
            resp = await self.matrix.request_room_key(event)
            if isinstance(resp, RoomKeyRequestResponse):
                self.log.info(f"Got Response for {resp.room_id}, start syncing")
                await self.matrix.sync(full_state=True)
                self.log.info("Finished sync")
            elif isinstance(resp, RoomKeyRequestError):
                self.log.error(f"Got Error for requesting room key: {resp}")

    async def invite_event(self, room: MatrixRoom, event: InviteMemberEvent):
        if not event.membership == "invite" or event.state_key != self.matrix.user_id:
            return

        self.log.debug(f"Invite Event for {room.name}")

        resp = await self.matrix.join(room.room_id)
        if isinstance(resp, JoinError):
            self.log.error(
                f"Can't Join {room.room_id} ({room.encrypted}): {JoinError.message}")
            return

        await self.matrix.sync()
        self.log.debug(f"Joined room {room.name}")

        await self.send_response(room.room_id, self.bot.handle_input('Start', room.room_id))

        if room.member_count > 2:
            await self.send_response(room.room_id, [BotResponse("Noch ein Hinweis: Da wir hier nicht zu zweit sind reagiere ich nur auf mentions!")])

    async def room_event(self, room: MatrixRoom, event: RoomMemberEvent):
        self.log.debug(f"Got RoomEvent: {event}")
        if event.membership == "leave" and event.state_key != self.matrix.user_id:
            if room.member_count == 1:
                resp = await self.matrix.room_leave(room.room_id)
                self.log.debug(f"Left room: {resp}")
                if isinstance(resp, RoomLeaveResponse):
                    self.bot.delete_user(room.room_id)

    @prometheus_async.aio.time(BOT_RESPONSE_TIME)
    async def handle_message(self, room: MatrixRoom, event: RoomMessageText):
        if self.identifier == event.sender:
            self.log.debug("Skipped message from myself")
            return

        # We need a mention in group rooms to handle messages
        if event.body.startswith(self.display_name):
            event.body = event.body[len(self.display_name) + 1:].strip()
        else:
            if room.member_count > 2:
                self.log.debug(
                    f"Skipped message in a group without mention: {event.body}")
                return

        RECV_MESSAGE_COUNT.inc()
        self.log.debug(f"Received from {room.room_id}: {event}")
        await self.send_response(room.room_id,
                                 self.bot.handle_input(event.body, room.room_id))

    async def send_response(self, room_id: str, responses: List[BotResponse]):
        # Check if device is verified
        # if self.matrix.room_contains_unverified(room.room_id):
        #    devices = self.matrix.room_devices(room.room_id)
        #    for user in devices:
        #        for device in devices[user]:
        #            self.matrix.verify_device(devices[user][device])
        #            self.log.debug(f"Verified {device} of {user}")

        if self.debug:
            return

        for message in responses:
            if message.images:
                for image in message.images:
                    # Calculate metadata
                    mime_type = "image/jpeg"
                    file_stat = os.stat(image)

                    im = Image.open(image)
                    (width, height) = im.size

                    url = await self.upload_file(image, mime_type)

                    image = {
                        "body": os.path.basename(image),
                        "msgtype": "m.image",
                        "url": url,
                        "info": {
                            "size": file_stat.st_size,
                            "mimetype": mime_type,
                            "w": width,  # width in pixel
                            "h": height,  # height in pixel
                        },
                    }

                    resp = await self.matrix.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=image,
                        ignore_unverified_devices=True
                    )
                    if isinstance(resp, ErrorResponse):
                        self.log.error(f"Could not send image: {resp}")
                    else:
                        SENT_IMAGES_COUNT.inc()

            resp = await self.matrix.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": adapt_text(str(message), just_strip=True),
                    "format": "org.matrix.custom.html",
                    "formatted_body": str(message).replace("\n", "<br />")
                },
                ignore_unverified_devices=True
            )
            if isinstance(resp, ErrorResponse):
                self.log.error(f"Could not send message: {resp}")
                FAILED_MESSAGE_COUNT.inc()
            else:
                SENT_MESSAGE_COUNT.inc()

    async def upload_file(self, path: str, mime_type: str) -> Optional[str]:
        file_stat = os.stat(path)

        async with aiofiles.open(path, "r+b") as f:
            resp, maybe_keys = await self.matrix.upload(
                f,
                content_type=mime_type,
                filename=os.path.basename(path),
                filesize=file_stat.st_size)

        if not isinstance(resp, UploadResponse):
            self.log.error(f"Failed to upload file. Failure response: {resp}")
            return None

        return resp.content_uri

    async def async_run(self) -> None:
        # Needed to update all room members etc.
        self.log.debug("Start first full sync")
        await self.matrix.sync(full_state=True)
        self.log.debug("Finished first sync")

        self.log.debug("Check profile for completeness")
        profile = await self.matrix.get_profile(self.identifier)
        if profile.displayname != self.display_name:
            resp = await self.matrix.set_displayname(self.display_name)
            if isinstance(resp, ProfileSetDisplayNameError):
                self.log.error(f"Cant set display name: {resp}")
            else:
                self.log.debug(f"Set display name to {self.display_name}")

        if profile.avatar_url is None:
            url = await self.upload_file(self.avatar_path, "image/png")
            if url is not None:
                resp = await self.matrix.set_avatar(url)
                if isinstance(resp, ProfileSetAvatarError):
                    self.log.error(f"Can't set avatar: {resp}")
                else:
                    self.log.debug(f"Set avatar to {url}")
        await self.matrix.sync_forever(timeout=300)

    def run(self):
        asyncio.get_event_loop().run_until_complete(self.async_run())

    async def send_unconfirmed_reports(self) -> None:
        unconfirmed_reports = self.bot.get_available_user_messages()

        if unconfirmed_reports:
            await self.matrix.sync(full_state=True)

        for report, userid, message in unconfirmed_reports:
            await self.send_response(userid, message)
            self.bot.confirm_message_send(report, userid)
            self.log.warning(f"Sent report to {userid}")

        await self.matrix.close()

    async def send_message_to_users(self, message: str, users: List[Union[str, int]]):
        for user in users:
            await self.send_response(user, [BotResponse(message)])
