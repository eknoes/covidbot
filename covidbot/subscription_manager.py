from datetime import datetime
from typing import List, Optional, Tuple

from mysql.connector import MySQLConnection


class SubscriptionManager(object):
    connection: MySQLConnection

    def __init__(self, db_connection: MySQLConnection):
        self.connection = db_connection
        self._create_db()

    def _create_db(self):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS bot_user '
                           '(user_id INTEGER PRIMARY KEY, last_update DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6))')
            cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                           '(user_id INTEGER, rs INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'UNIQUE(user_id, rs), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')
            self.connection.commit()

    def add_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('INSERT INTO bot_user (user_id) VALUES (%s) '
                           'ON DUPLICATE KEY UPDATE user_id=user_id', [user_id])
            cursor.execute('INSERT INTO subscriptions (user_id, rs) VALUES (%s, %s) '
                           'ON DUPLICATE KEY UPDATE user_id=user_id', [user_id, rs])
            self.connection.commit()
            if cursor.rowcount == 1:
                return True
        return False

    def rm_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM subscriptions WHERE user_id=%s AND rs=%s', [user_id, rs])
            self.connection.commit()
            if cursor.rowcount == 0:
                return False

            if len(self.get_subscriptions(user_id)) == 0:
                self.delete_user(user_id)

            return True

    def get_subscriptions(self, user_id: int) -> Optional[List[int]]:
        result = []
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT rs FROM subscriptions WHERE user_id=%s', [user_id])
            for row in cursor.fetchall():
                result.append(row['rs'])
        return result

    def delete_user(self, user_id: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM subscriptions WHERE user_id=%s', [user_id])
            cursor.execute('DELETE FROM bot_user WHERE user_id=%s', [user_id])
            self.connection.commit()
            if cursor.rowcount > 0:
                return True
        return False

    def get_all_user(self) -> List[int]:
        result = []
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT user_id FROM bot_user')
            for row in cursor.fetchall():
                result.append(row['user_id'])
        return result

    def set_last_update(self, user_id: int, date: datetime):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET last_update=%s WHERE user_id=%s", [date, user_id])
            self.connection.commit()

    def get_last_update(self, user_id: int) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT last_update FROM bot_user WHERE user_id=%s", [user_id])
            row = cursor.fetchone()
            if row is not None and 'last_update' in row:
                return row['last_update']

    def get_total_user(self) -> int:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT COUNT(user_id) as user_num FROM bot_user")
            row = cursor.fetchone()
            if row is not None and 'user_num' in row:
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
