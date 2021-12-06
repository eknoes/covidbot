import asyncio
import datetime
import logging
from typing import List, Union

import nio
from nio import AsyncClient, AsyncClientConfig, RoomMessageText, MatrixRoom, MegolmEvent, \
    RoomKeyEvent, Event, InviteMemberEvent, RoomMemberEvent, RoomKeyRequestResponse, \
    JoinError, RoomKeyRequestError
from nio.store import SqliteStore

from covidbot.bot import Bot
from covidbot.interfaces.bot_response import BotResponse
from covidbot.interfaces.messenger_interface import MessengerInterface


class MatrixInterface(MessengerInterface):
    username: str

    matrix: AsyncClient
    bot: Bot

    log = logging.getLogger(__name__)

    def __init__(self, bot: Bot, home_server: str, username: str, access_token: str, device_id: str):
        self.username = f"@{username}:{home_server[home_server.find('//')+2:]}"

        self.matrix = AsyncClient(home_server, username, device_id, store_path=".",
                                  config=AsyncClientConfig(encryption_enabled=True,
                                                           store=SqliteStore,
                                                           store_name="matrix.db",
                                                           store_sync_tokens=True))
        self.matrix.access_token = access_token
        self.matrix.user_id = self.username

        self.matrix.add_event_callback(self.handle_message, RoomMessageText)
        self.matrix.add_event_callback(self.crypto_event, MegolmEvent)
        self.matrix.add_event_callback(self.invite_event, InviteMemberEvent)
        self.matrix.add_event_callback(self.room_event, RoomMemberEvent)
        self.matrix.add_event_callback(self.other_event, Event)

        self.matrix.load_store()
        self.bot = bot

        self.log.level = logging.DEBUG
        self.log.debug(f"Initialized Matrix Bot: {self.username}")

    async def send_unconfirmed_reports(self) -> None:
        pass

    async def send_message_to_users(self, message: str, users: List[Union[str, int]]):
        pass

    async def other_event(self, room: MatrixRoom, event: Event):
        self.log.warning(f"Received unknown Event: {type(event)}")

    async def crypto_event(self, room: MatrixRoom, event: MegolmEvent):
        self.log.warning(f"Can't decrypt for {room.name}")
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
            self.log.error(f"Can't Join {room.room_id} ({room.encrypted}): {JoinError.message}")

        await self.matrix.sync()

        self.log.debug(f"Joined room {room.name}")

    async def room_event(self, room: MatrixRoom, event: RoomMemberEvent):
        self.log.info(f"Got RoomEvent: {event}")

    async def handle_message(self, room: MatrixRoom, event: RoomMessageText):
        if self.username == event.sender:
            self.log.debug("Skipped message from myself")
            return

        self.log.info(f"Received from {room.room_id}: {event}")
        await self.send_response(room.room_id, self.bot.handle_input(event.body, room.room_id))

    async def send_response(self, room_id, responses: List[BotResponse]):
        for message in responses:
            if message.images:
                for image in message.images:
                    pass

            await self.matrix.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content = {
                    "msgtype": "m.text",
                    "body": message.message
                }
            )

    async def async_run(self) -> None:
        await self.matrix.sync_forever(timeout=300)

    def run(self):
        asyncio.get_event_loop().run_until_complete(self.async_run())
