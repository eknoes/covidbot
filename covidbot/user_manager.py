import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Union

from mysql.connector import MySQLConnection, IntegrityError


@dataclass
class BotUser:
    id: int
    platform_id: Union[int, str]
    last_update: datetime
    language: str
    subscriptions: Optional[List[int]] = None
    activated: bool = False


class UserManager(object):
    connection: MySQLConnection
    platform: str
    log = logging.getLogger(__name__)
    activated_default: bool

    def __init__(self, platform: str, db_connection: MySQLConnection, activated_default=False):
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
                           'last_update DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),'
                           'language VARCHAR(20) DEFAULT NULL, created DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),'
                           'platform_id VARCHAR(100), platform VARCHAR(20),'
                           'sent_report DATETIME(6) DEFAULT NULL, '
                           'activated TINYINT(1) DEFAULT FALSE NOT NULL, UNIQUE(platform_id, platform))')
            cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                           '(user_id INTEGER, rs INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'UNIQUE(user_id, rs), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_feedback '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, user_id INTEGER,'
                           'added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), feedback TEXT NOT NULL, '
                           'replied TINYINT(1) NOT NULL DEFAULT 0, forwarded TINYINT(1) NOT NULL DEFAULT 0, '
                           'FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS answered_messages '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, platform VARCHAR(20), message_id BIGINT, '
                           'UNIQUE(platform, message_id))')
            self.connection.commit()

    def set_user_activated(self, user_id: int, activated=True) -> None:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET activated=%s WHERE user_id=%s", [activated, user_id])
            if cursor.rowcount != 1:
                self.log.warning("Activate user did not update exactly one user")
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

    def get_all_user(self, with_subscriptions=False, filter_id=None) -> List[BotUser]:
        result = []
        with self.connection.cursor(dictionary=True) as cursor:
            if with_subscriptions:
                query = ("SELECT bot_user.user_id, platform_id, last_update, language, rs, activated FROM bot_user "
                         "LEFT JOIN subscriptions s on bot_user.user_id = s.user_id "
                         "WHERE platform=%s")
            else:
                query = "SELECT bot_user.user_id, platform_id, last_update, language, activated FROM bot_user WHERE platform=%s"
            args = [self.platform]

            if filter_id:
                query += " AND bot_user.user_id=%s"
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
                                           last_update=row['last_update'], language=language,
                                           activated=row['activated'])

                if with_subscriptions:
                    if not current_user.subscriptions:
                        current_user.subscriptions = []

                    if row['rs']:
                        current_user.subscriptions.append(row['rs'])

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
            cursor.execute('DELETE FROM user_feedback WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM bot_user WHERE user_id=%s', [user_id])
            self.connection.commit()
            if cursor.rowcount > 0:
                return True
        return False

    def set_last_update(self, user_id: int, last_update: datetime) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET last_update=%s, sent_report=%s WHERE user_id=%s",
                           [last_update, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id])
            if cursor.rowcount == 0:
                return False
            self.connection.commit()
            return True

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
                cursor.execute("INSERT INTO bot_user SET platform_id=%s, platform=%s, activated=%s,"
                               "last_update=(SELECT MAX(date) FROM covid_data)",
                               [identifier, self.platform, self.activated_default])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    return cursor.lastrowid
            except IntegrityError:
                return False
            return False

    def get_total_user_number(self) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as user_num FROM bot_user WHERE platform NOT LIKE 'twitter' "
                           "AND platform NOT LIKE 'interactive'")
            row = cursor.fetchone()
            if row and 'user_num' in row and row['user_num']:
                return row['user_num']
            return 0

    def get_user_number(self, platform: str) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as user_num FROM bot_user WHERE platform=%s", [platform])
            row = cursor.fetchone()
            if row and 'user_num' in row and row['user_num']:
                return row['user_num']
            return 0

    def get_ranked_subscriptions(self) -> List[Tuple[int, str]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(subscriptions.user_id) as subscribers, c.county_name FROM subscriptions "
                           "JOIN counties c on subscriptions.rs = c.rs GROUP BY c.county_name "
                           "ORDER BY subscribers DESC LIMIT 10")
            result = []
            for row in cursor.fetchall():
                result.append((row['subscribers'], row['county_name']))
            result.sort(key=lambda x: x[0], reverse=True)
            return result

    def get_mean_subscriptions(self) -> float:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(*)/COUNT(DISTINCT user_id) as mean FROM subscriptions ORDER BY user_id "
                           "LIMIT 1")
            row = cursor.fetchone()

            if row['mean']:
                return row['mean']
            return 1.0

    def get_most_subscriptions(self) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(rs) as num_subscriptions FROM subscriptions "
                           "GROUP BY user_id ORDER BY num_subscriptions DESC LIMIT 1")
            row = cursor.fetchone()

            if row and row['num_subscriptions']:
                return row['num_subscriptions']
            return 0

    def get_users_per_platform(self) -> List[Tuple[str, int]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as c, platform FROM bot_user WHERE platform NOT LIKE 'interactive' "
                           "AND platform NOT LIKE 'twitter' "
                           "GROUP BY platform ORDER BY c DESC")
            results = []
            for row in cursor.fetchall():
                results.append((str(row['platform']).capitalize(), row['c']))
            return results

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

    def get_not_forwarded_feedback(self) -> List[Tuple[int, str]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, feedback, platform, platform_id, user_feedback.user_id, user_feedback.added FROM user_feedback "
                "LEFT JOIN bot_user bu on bu.user_id = user_feedback.user_id "
                "WHERE forwarded=0")
            results = []
            for row in cursor.fetchall():
                feedback = f"<b>Neues Feedback von {row['user_id']}</b>\n" \
                           f"{row['feedback']}\n\n" \
                           f"Datum: {row['added']}\n" \
                           f"Plattform: {row['platform']}\n" \
                           f"Plattform ID: {row['platform_id']}\n" \
                           f"Befehl zum Antworten:\n" \
                           f"<code>python -m covidbot --message-user --platform {row['platform']} --specific {row['platform_id']}" \
                           f"</code>"
                results.append((row['id'], feedback))
            return results

    def confirm_feedback_forwarded(self, feedback_id: int):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE user_feedback SET forwarded=1 WHERE id=%s", [feedback_id])

    def rm_feedback(self, feedback_id) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM user_feedback WHERE id=%s', [feedback_id])
            if cursor.rowcount == 1:
                self.connection.commit()
                return True
            return False

    def is_message_answered(self, message_id: int) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT id FROM answered_messages WHERE message_id=%s', [message_id])
            if cursor.fetchone():
                return True
            return False

    def set_message_answered(self, message_id: int):
        with self.connection.cursor() as cursor:
            cursor.execute('INSERT INTO answered_messages (platform, message_id) VALUES (%s, %s)',
                           [self.platform, message_id])
        self.connection.commit()
