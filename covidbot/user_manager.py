from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from mysql.connector import MySQLConnection, IntegrityError


@dataclass
class BotUser:
    id: int
    last_update: datetime
    language: str
    subscriptions: Optional[List[int]] = None


class UserManager(object):
    connection: MySQLConnection

    def __init__(self, db_connection: MySQLConnection):
        self.connection = db_connection
        self._create_db()

    def _create_db(self):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS bot_user '
                           '(user_id INTEGER PRIMARY KEY, last_update DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'language VARCHAR(20) DEFAULT NULL)')
            cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                           '(user_id INTEGER, rs INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'UNIQUE(user_id, rs), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            cursor.execute('CREATE TABLE IF NOT EXISTS user_feedback '
                           '(id INT AUTO_INCREMENT PRIMARY KEY, user_id INTEGER,'
                           'added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), feedback TEXT NOT NULL,'
                           'FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            self.connection.commit()

    def add_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute('INSERT INTO subscriptions (user_id, rs) VALUES (%s, %s) '
                               'ON DUPLICATE KEY UPDATE user_id=user_id', [user_id, rs])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    return True
            except IntegrityError:
                if self.create_user(user_id):
                    return self.add_subscription(user_id, rs)
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
                query = ("SELECT bot_user.user_id, last_update, language, rs FROM bot_user "
                         "LEFT JOIN subscriptions s on bot_user.user_id = s.user_id")
            else:
                query = "SELECT bot_user.user_id, last_update, language FROM bot_user"

            if filter_id:
                query += " WHERE bot_user.user_id=%s"
            query += " ORDER BY bot_user.user_id"

            if filter_id:
                cursor.execute(query, [filter_id])
            else:
                cursor.execute(query)

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

                    current_user = BotUser(id=row['user_id'], last_update=row['last_update'], language=language)

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

    def create_user(self, user_id: int, last_update=datetime.today(), language=None) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute("INSERT INTO bot_user SET user_id=%s, last_update=%s, language=%s",
                               [user_id, last_update, language])
                if cursor.rowcount == 1:
                    self.connection.commit()
                    return True
            except IntegrityError:
                pass

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
                           "ORDER BY subscribers DESC LIMIT 5")
            result = []
            for row in cursor.fetchall():
                result.append((row['subscribers'], row['county_name']))
            result.sort(key=lambda x: x[0], reverse=True)
            return result

    def add_feedback(self, user_id: int, feedback: str) -> Optional[int]:
        if not feedback:
            return None

        if not self.get_user(user_id):
            self.create_user(user_id)

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

