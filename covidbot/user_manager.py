from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any, Union

from mysql.connector import MySQLConnection, IntegrityError


@dataclass
class BotUser:
    id: int
    platform_id: Union[int, str]
    last_update: datetime
    language: str
    subscriptions: Optional[List[int]] = None


class UserManager(object):
    connection: MySQLConnection
    platform: str

    def __init__(self, platform: str, db_connection: MySQLConnection):
        self.connection = db_connection
        self._create_db()
        self.platform = platform

    def _create_db(self):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS bot_user '
                           '(user_id INTEGER PRIMARY KEY AUTO_INCREMENT, '
                           'last_update DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),'
                           'language VARCHAR(20) DEFAULT NULL, created DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),'
                           'platform_id VARCHAR(100), platform VARCHAR(10), UNIQUE(platform_id, platform))')
            cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                           '(user_id INTEGER, rs INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'UNIQUE(user_id, rs), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_feedback '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, user_id INTEGER,'
                           'added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), feedback TEXT NOT NULL,'
                           'FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
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
                query = ("SELECT bot_user.user_id, bot_user.platform_id, last_update, language, rs FROM bot_user "
                         "LEFT JOIN subscriptions s on bot_user.user_id = s.user_id "
                         "WHERE platform=%s")
            else:
                query = "SELECT bot_user.user_id, last_update, language FROM bot_user WHERE platform=%s"
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
                                           last_update=row['last_update'], language=language)

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
            cursor.execute("UPDATE bot_user SET last_update=%s WHERE user_id=%s", [last_update, user_id])
            if cursor.rowcount == 0:
                return self.create_user(user_id, last_update=last_update)
            self.connection.commit()
            return True

    def set_language(self, user_id: int, language: str) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET language=%s WHERE user_id=%s", [language, user_id])
            if cursor.rowcount == 0:
                return self.create_user(user_id, language=language)
            self.connection.commit()
            return True

    def create_user(self, identifier: str, last_update=datetime.today(), language=None) -> Union[int, bool]:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute("INSERT INTO bot_user SET platform_id=%s, platform=%s, last_update=%s, language=%s",
                               [identifier, self.platform, last_update, language])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    return cursor.lastrowid
            except IntegrityError:
                return False
            return False

    def get_total_user_number(self) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as user_num FROM bot_user")
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

    def rm_feedback(self, feedback_id) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM user_feedback WHERE id=%s', [feedback_id])
            if cursor.rowcount == 1:
                self.connection.commit()
                return True
            return False
