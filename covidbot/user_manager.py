import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Union, Generator

from mysql.connector import MySQLConnection, IntegrityError, OperationalError

from covidbot.settings import BotUserSettings
from covidbot.utils import MessageType


@dataclass
class BotUser:
    id: int
    platform_id: Union[int, str]
    language: str
    created: datetime
    subscribed_reports: Optional[List[MessageType]] = None
    subscriptions: Optional[List[int]] = None
    activated: bool = False


class UserManager(object):
    connection: MySQLConnection
    platform: str
    log = logging.getLogger(__name__)
    activated_default: bool

    def __init__(self, platform: str, db_connection: MySQLConnection, activated_default=True):
        self.connection = db_connection
        self._create_db()
        self.platform = platform
        self.activated_default = activated_default
        self.log.debug(f"UserManager for {platform} initialized")

    def _create_db(self):
        self.log.debug("Creating Tables")
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS bot_user '
                           '(user_id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'language VARCHAR(20) DEFAULT NULL, created DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),'
                           'platform_id VARCHAR(100), platform VARCHAR(20),'
                           'activated TINYINT(1) DEFAULT FALSE NOT NULL, UNIQUE(platform_id, platform))')
            cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                           '(user_id INTEGER, rs INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'UNIQUE(user_id, rs), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_feedback '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, user_id INTEGER,'
                           'added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), feedback TEXT NOT NULL, is_read'
                           ' TINYINT(1) NOT NULL DEFAULT 0, is_tagged TINYINT(1) NOT NULL DEFAULT 0,'
                           'notification_sent TINYINT(1) NOT NULL DEFAULT 0, '
                           'FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_responses '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, receiver_id INT NOT NULL, '
                           'created DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), sent DATETIME(6) DEFAULT NULL,'
                           'message TEXT, hidden TINYINT(1) DEFAULT 0, FOREIGN KEY(receiver_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_ticket_tag '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, '
                           'created DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),'
                           'tag VARCHAR(100), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS answered_messages '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, platform VARCHAR(20), message_id BIGINT, '
                           'UNIQUE(platform, message_id))')
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS platform_statistics (platform VARCHAR(100) PRIMARY KEY, followers INTEGER)')
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS bot_user_settings (id INTEGER PRIMARY KEY AUTO_INCREMENT, user_id INTEGER '
                'NOT NULL, setting VARCHAR(100), value TINYINT(1), UNIQUE(user_id, setting), FOREIGN KEY(user_id) '
                'REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS bot_user_sent_reports (id INTEGER PRIMARY KEY AUTO_INCREMENT,'
                           ' user_id INTEGER NOT NULL, sent_report DATETIME DEFAULT NOW(), report VARCHAR(40),'
                           ' FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS report_subscriptions '
                           '(user_id INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'report VARCHAR(40) NOT NULL, '
                           'UNIQUE(user_id, report), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            self.connection.commit()

    def set_user_activated(self, user_id: int, activated=True) -> None:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET activated=%s WHERE user_id=%s", [activated, user_id])
            if cursor.rowcount != 1:
                self.log.warning(f"Activate user did not update exactly one user but {cursor.rowcount}")
            self.connection.commit()

    def get_user_id(self, identifier: str, create_if_not_exists=True) -> Optional[int]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT user_id FROM bot_user WHERE platform=%s AND platform_id=%s",
                           [self.platform, identifier])
            row = cursor.fetchone()
            if row:
                return row['user_id']
            if create_if_not_exists:
                new_id = self.create_user(identifier)
                if not new_id:
                    raise IntegrityError("Either a user_id should be available, or creating a user should return an ID")
                return new_id
            return None

    def change_platform_id(self, old_id: str, new_id: str) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute("UPDATE bot_user SET platform_id=%s WHERE platform_id=%s", [new_id, old_id])
                if cursor.rowcount:
                    return True
            except IntegrityError:
                pass
            return False

    def add_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute('INSERT INTO subscriptions (user_id, rs) VALUES (%s, %s)', [user_id, rs])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    return True
            except IntegrityError:
                return False
            return False

    def rm_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM subscriptions WHERE user_id=%s AND rs=%s', [user_id, rs])
            self.connection.commit()
            if cursor.rowcount == 0:
                return False
            return True

    def add_report_subscription(self, user_id: int, report: MessageType) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute('INSERT INTO report_subscriptions (user_id, report) VALUES (%s, %s)', [user_id, report.value])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    return True
            except IntegrityError:
                return False
            return False

    def rm_report_subscription(self, user_id: int, report: MessageType) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM report_subscriptions WHERE user_id=%s AND report=%s', [user_id, report.value])
            self.connection.commit()
            if cursor.rowcount == 0:
                return False
            return True

    def get_all_user(self, with_subscriptions=False, filter_id=None, all_platforms=False) -> List[BotUser]:
        result = []
        with self.connection.cursor(dictionary=True) as cursor:
            args = []
            if with_subscriptions:
                query = ("SELECT bot_user.user_id, platform_id, created, language, rs, activated, report FROM bot_user "
                         "LEFT JOIN subscriptions s on bot_user.user_id = s.user_id "
                         "LEFT JOIN report_subscriptions r on bot_user.user_id = r.user_id")
                
            else:
                query = "SELECT user_id, platform_id, language, activated, created " \
                        "FROM bot_user"

            if not all_platforms:
                query += " WHERE platform=%s"
                args.append(self.platform)

            if filter_id:
                if not all_platforms:
                    query += " AND bot_user.user_id=%s"
                else:
                    query += " WHERE bot_user.user_id=%s"
                args.append(filter_id)
            query += " ORDER BY bot_user.user_id"

            cursor.execute(query, args)

            current_user: Optional[BotUser] = None
            for row in cursor.fetchall():
                if not current_user or current_user.id != row['user_id']:
                    if current_user:
                        result.append(current_user)

                    # de as default language
                    if not row['language']:
                        language = "de"
                    else:
                        language = row['language']

                    current_user = BotUser(id=row['user_id'], platform_id=row['platform_id'],
                                           language=language, activated=row['activated'], created=row['created'])

                if with_subscriptions:
                    if not current_user.subscriptions:
                        current_user.subscriptions = []

                    if row['rs'] is not None and row['rs'] not in current_user.subscriptions:
                        current_user.subscriptions.append(row['rs'])

                    if not current_user.subscribed_reports:
                        current_user.subscribed_reports = []

                    if row['report'] is not None and MessageType(row['report']) not in current_user.subscribed_reports:
                        current_user.subscribed_reports.append(MessageType(row['report']))

            if current_user:
                result.append(current_user)

        return result

    def get_user(self, user_id: int, with_subscriptions=False) -> Optional[BotUser]:
        result = self.get_all_user(filter_id=user_id, with_subscriptions=with_subscriptions)
        if result:
            return result[0]

    def delete_user(self, user_id: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM subscriptions WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM report_subscriptions WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM user_feedback WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM bot_user_settings WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM bot_user_sent_reports WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM user_responses WHERE receiver_id=%s', [user_id])
            cursor.execute('DELETE FROM user_ticket_tag WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM bot_user WHERE user_id=%s', [user_id])
            self.connection.commit()
            if cursor.rowcount > 0:
                return True
        return False

    def add_sent_report(self, user_id: int, report: MessageType) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute("INSERT INTO bot_user_sent_reports (user_id, report, sent_report) VALUE (%s, %s, NOW())",
                               [user_id, report.value])
                self.connection.commit()
                if cursor.rowcount == 0:
                    return False
                return True
            except IntegrityError as e:
                self.log.error(f"Can't add sent report for {user_id}:\n{e}", exc_info=e)

    def get_last_updates(self, user_id: int, report: MessageType) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT sent_report FROM bot_user_sent_reports WHERE user_id=%s AND report=%s '
                           'ORDER BY sent_report DESC LIMIT 1', [user_id, report.value])
            row = cursor.fetchone()
            if row:
                return row['sent_report']

    def set_language(self, user_id: int, language: str) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET language=%s WHERE user_id=%s", [language, user_id])
            if cursor.rowcount == 0:
                return False
            self.connection.commit()
            return True

    def create_user(self, identifier: str) -> Union[int, bool]:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute("INSERT INTO bot_user SET platform_id=%s, platform=%s, activated=%s",
                               [identifier, self.platform, self.activated_default])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    user_id = cursor.lastrowid
                    cursor.execute("INSERT INTO report_subscriptions (user_id, report) VALUE (%s, %s)",
                                   [user_id, MessageType.CASES_GERMANY.value])
                    cursor.execute("INSERT INTO bot_user_sent_reports (user_id, report) VALUE (%s, %s)",
                                   [user_id, MessageType.CASES_GERMANY.value])
                    return user_id
            except IntegrityError:
                return False
            return False

    def get_messenger_user_number(self) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as user_num FROM bot_user "
                           "WHERE platform NOT IN ('interactive', 'twitter', 'mastodon', 'instagram', 'facebook') "
                           "AND activated=1")
            row = cursor.fetchone()
            if row and 'user_num' in row and row['user_num']:
                return row['user_num']
            return 0

    def get_total_user_number(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT SUM(followers) FROM platform_statistics')
            row = cursor.fetchone()
            if not row or not row[0]:
                return 0 + self.get_messenger_user_number()
            return row[0] + self.get_messenger_user_number()

    def get_user_number(self, platform: str) -> int:
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT COUNT(user_id) as user_num FROM bot_user WHERE platform=%s AND activated=1", [platform])
                row = cursor.fetchone()
                if row and 'user_num' in row and row['user_num']:
                    return row['user_num']
                return 0
        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_user_number(platform)

    def get_ranked_subscriptions(self) -> List[Tuple[int, str]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(subscriptions.user_id) as subscribers, c.county_name FROM subscriptions "
                           "JOIN counties c on subscriptions.rs = c.rs "
                           "WHERE subscriptions.rs != 0 "
                           "GROUP BY c.county_name "
                           "ORDER BY subscribers DESC LIMIT 10")
            result = []
            for row in cursor.fetchall():
                result.append((row['subscribers'], row['county_name']))
            result.sort(key=lambda x: x[0], reverse=True)
            return result

    def get_mean_subscriptions(self) -> float:
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT COUNT(*)/COUNT(DISTINCT user_id) as mean FROM subscriptions ORDER BY user_id "
                               "LIMIT 1")
                row = cursor.fetchone()

                if row['mean']:
                    return row['mean']
                return 1.0
        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_mean_subscriptions()

    def get_most_subscriptions(self) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(rs) as num_subscriptions FROM subscriptions "
                           "GROUP BY user_id ORDER BY num_subscriptions DESC LIMIT 1")
            row = cursor.fetchone()

            if row and row['num_subscriptions']:
                return row['num_subscriptions']
            return 0

    def get_users_per_messenger(self) -> List[Tuple[str, int]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as c, platform FROM bot_user "
                           "WHERE platform NOT IN ('interactive', 'twitter', 'mastodon', 'instagram', 'facebook') "
                           "AND activated=1 "
                           "GROUP BY platform ORDER BY c DESC")
            results = []
            for row in cursor.fetchall():
                results.append((str(row['platform']).capitalize(), row['c']))
            return results

    def get_users_per_network(self) -> List[Tuple[str, int]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM platform_statistics ORDER BY followers DESC")
            results = []
            for row in cursor.fetchall():
                results.append((str(row['platform']).capitalize(), row['followers']))
            return results

    def add_user_message(self, recipient_id: int, message: str):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('INSERT INTO user_responses (receiver_id, message, hidden) VALUE (%s, %s, 1)', [recipient_id, message])
        self.connection.commit()

    def get_user_messages(self, user_id: int) -> List[str]:
        messages = []
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT message FROM user_responses WHERE receiver_id=%s AND sent IS NULL", [user_id])
            for m in cursor.fetchall():
                messages.append(m['message'])
        return messages

    def confirm_user_messages_sent(self, user_id: int):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('UPDATE user_responses SET sent=CURRENT_TIMESTAMP() WHERE receiver_id=%s AND sent IS NULL',
                           [user_id])

    def add_feedback(self, user_id: int, feedback: str) -> Optional[int]:
        if not feedback:
            return None

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('INSERT INTO user_feedback (user_id, feedback) VALUES (%s, %s)', [user_id, feedback])
            if cursor.rowcount == 1:
                new_id = cursor.lastrowid
                self.connection.commit()
                return new_id
            return None

    def get_feedback_notifications(self) -> Generator[str, None, None]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT id, user_id, feedback FROM user_feedback WHERE notification_sent=0 and is_read=0 '
                           'ORDER BY added')
            for row in cursor.fetchall():
                yield f"<b>Neues Feedback von {row['user_id']}</b>\n" \
                      f"{row['feedback']}\n\n" \
                      f"Antworten: https://covidbot.d-64.org/feedback/user/{row['user_id']}"
                cursor.execute('UPDATE user_feedback SET notification_sent=1 WHERE id=%s', [row['id']])
        self.connection.commit()

    def is_message_answered(self, message_id: int) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT id FROM answered_messages WHERE message_id=%s', [message_id])
            if cursor.fetchall():
                return True
            return False

    def set_message_answered(self, message_id: int):
        with self.connection.cursor() as cursor:
            cursor.execute('INSERT INTO answered_messages (platform, message_id) VALUES (%s, %s)',
                           [self.platform, message_id])
        self.connection.commit()

    def set_social_network_user_number(self, number_of_users: int):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('INSERT INTO platform_statistics (platform, followers) VALUE (%s, %s) ON DUPLICATE '
                           'KEY UPDATE followers=%s', [self.platform, number_of_users, number_of_users])
        self.connection.commit()

    def get_social_network_user_number(self, network: str):
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute('SELECT followers FROM platform_statistics WHERE platform=%s LIMIT 1', [network])
                rows = cursor.fetchall()
                if rows:
                    return rows[0]['followers']
                return 0
        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_social_network_user_number(network)

    def set_user_setting(self, user_id: int, setting: BotUserSettings, value: bool):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('INSERT INTO bot_user_settings (user_id, setting, value) VALUE (%s, %s, %s) ON DUPLICATE '
                           'KEY UPDATE value=%s', [user_id, setting.value, value, value])

    def get_user_setting(self, user_id: int, setting: BotUserSettings) -> bool:
        default = BotUserSettings.default(setting)
        if user_id is None:
            return default

        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT value FROM bot_user_settings WHERE user_id=%s AND setting=%s', [user_id, setting.value])
            rows = cursor.fetchall()
            if not rows:
                # Change default if corresponding subscriptions exist
                if setting in [BotUserSettings.REPORT_INCLUDE_ICU, BotUserSettings.REPORT_INCLUDE_VACCINATION]:
                    user = self.get_user(user_id, with_subscriptions=True)
                    if user:
                        if setting == BotUserSettings.REPORT_INCLUDE_ICU and MessageType.ICU_GERMANY in user.subscribed_reports:
                            return False
                        elif setting == BotUserSettings.REPORT_INCLUDE_VACCINATION and MessageType.VACCINATION_GERMANY in user.subscribed_reports:
                            return False
                return default

            value = rows[0]['value']
            if value is None:
                return default

            return value
