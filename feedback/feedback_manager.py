import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Dict, Tuple, Optional

from mysql.connector import MySQLConnection


class CommunicationState(Enum):
    UNREAD = "unread"
    READ = "read"
    ANSWERED = "answered"


class TicketState(Enum):
    CREATED = "created"
    SENT = "sent"
    READ = "read"


@dataclass
class SingleTicket:
    author: int
    message: str
    date: datetime
    state: TicketState

    def meta_str(self) -> str:
        state_str = ""
        if self.state == TicketState.CREATED:
            state_str = "📤"
        elif self.state == TicketState.SENT:
            state_str = "✉️"
        elif self.state == TicketState.READ:
            state_str = "📃"

        return self.date.strftime("%d.%m.%Y %H:%M") + f' Uhr {state_str}'


@dataclass
class Communication:
    user_id: int
    platform: str
    messages: List[SingleTicket]
    tags: List[str]

    def last_communication(self) -> datetime:
        return self.messages[-1].date

    def last_communication_str(self) -> str:
        return self.messages[-1].date.strftime("%d.%m.%Y %H:%M")

    def get_tags_html(self) -> str:
        result = ""
        for t in self.tags:
            result += f'<span class="ticket-tag"><span class="ticket-tag-{t} ticket-color-tag"></span> {t.capitalize()}</span>'
        return result

    def state(self) -> CommunicationState:
        for i in range(len(self.messages), 0, -1):
            m = self.messages[i - 1]
            if m.author != 0 and m.state != TicketState.READ:
                return CommunicationState.UNREAD

        if self.messages[-1].author == 0:
            return CommunicationState.ANSWERED

        return CommunicationState.READ

    def desc(self) -> str:
        desc = self.messages[-1].message[:100]

        if len(desc) < len(self.messages[-1].message):
            desc += "..."
        return desc


class FeedbackManager(object):
    connection: MySQLConnection
    log = logging.getLogger(__name__)

    def __init__(self, db_connection: MySQLConnection):
        self.connection = db_connection

    def get_all_communication(self) -> Tuple[List[Communication], List[Communication], List[Communication]]:
        results: Dict[int, Communication]
        results = {}
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                "(SELECT b.user_id, b.platform, feedback, added, is_read, 1 as from_user FROM user_feedback "
                "LEFT JOIN bot_user b on b.user_id = user_feedback.user_id) "
                "UNION "
                "(SELECT receiver_id, bu.platform, message, user_responses.created, sent, 0 FROM user_responses "
                "LEFT JOIN bot_user bu on bu.user_id = user_responses.receiver_id WHERE hidden=0)")
            for row in cursor.fetchall():
                if not results.get(row['user_id']):
                    results[row['user_id']] = Communication(row['user_id'], row['platform'], [], [])

                author_id = row['user_id']
                if row['from_user'] == 0:
                    author_id = 0

                state = TicketState.SENT
                if row['is_read'] == '1' and row['from_user'] == 1:
                    state = TicketState.READ
                elif not row['is_read'] and row['from_user'] == 0:
                    state = TicketState.CREATED

                results[row['user_id']].messages.append(
                    SingleTicket(author_id, row['feedback'], row['added'], state))

        unread = []
        read = []
        answered = []
        for key, value in results.items():
            value.messages.sort(key=lambda x: x.date)
            value.tags = self.get_user_tags(value.user_id)
            if value.state() == CommunicationState.UNREAD:
                unread.append(value)
            elif value.state() == CommunicationState.ANSWERED:
                answered.append(value)
            elif value.state() == CommunicationState.READ:
                read.append(value)

        unread.sort(key=lambda x: x.last_communication(), reverse=True)
        read.sort(key=lambda x: x.last_communication(), reverse=True)
        answered.sort(key=lambda x: x.last_communication(), reverse=True)

        return unread, read, answered

    def mark_user_read(self, user_id: int):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE user_feedback SET is_read=1 WHERE user_id=%s', [user_id])

    def mark_user_unread(self, user_id: int):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE user_feedback SET is_read=0 WHERE user_id=%s', [user_id])

    def message_user(self, user_id: int, message: str):
        with self.connection.cursor() as cursor:
            cursor.execute('INSERT INTO user_responses (receiver_id, message) VALUE (%s, %s)', [user_id, message])

    def add_user_tag(self, user_id: int, tag: str):
        with self.connection.cursor() as cursor:
            cursor.execute('INSERT INTO user_ticket_tag (user_id, tag) VALUE (%s, %s)', [user_id, tag])

    def remove_user_tag(self, user_id: int, tag: str):
        with self.connection.cursor() as cursor:
            cursor.execute('DELETE FROM user_ticket_tag WHERE user_id=%s AND tag=%s', [user_id, tag])

    def get_user_tags(self, user_id: int) -> List[str]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT tag FROM user_ticket_tag WHERE user_id=%s", [user_id])
            tags = []
            for r in cursor.fetchall():
                tags.append(r[0])
            return tags

    def get_user_subscriptions(self, user_id: int) -> List[str]:
        with self.connection.cursor() as cursor:
            results = []
            cursor.execute("SELECT c.rs, c.county_name, subscriptions.added FROM subscriptions "
                           "LEFT JOIN counties c on subscriptions.rs = c.rs "
                           "WHERE user_id=%s", [user_id])
            for r in cursor.fetchall():
                results.append(f"{r[1]} (seit {r[2].strftime('%d.%m.%Y')})")
            return results

    def get_user_report_subscriptions(self, user_id: int) -> List[str]:
        with self.connection.cursor() as cursor:
            results = []
            cursor.execute("SELECT report, added FROM report_subscriptions "
                           "WHERE user_id=%s", [user_id])
            for r in cursor.fetchall():
                results.append(f"{r[0]} (seit {r[1].strftime('%d.%m.%Y')})")
            return results

    @staticmethod
    def get_available_tags() -> List[str]:
        return ["hilfe", "idee", "bug", "lob", "sönke", "erik"]
