from datetime import datetime
from typing import List, Optional

from mysql.connector import MySQLConnection

from covidbot.file_based_subscription_manager import FileBasedSubscriptionManager


class SubscriptionManager(object):
    connection: MySQLConnection

    def __init__(self, db_connection: MySQLConnection):
        self.connection = db_connection
        self._create_db()

    def _create_db(self):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS bot_user '
                           '(user_id INTEGER PRIMARY KEY, last_update DATETIME(6) DEFAULT NULL)')
            cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                           '(user_id INTEGER, rs INTEGER, added DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6), '
                           'UNIQUE(user_id, rs), FOREIGN KEY(user_id) REFERENCES bot_user(user_id))')

    def add_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('INSERT INTO bot_user (user_id) VALUES (%s) '
                           'ON DUPLICATE KEY UPDATE user_id=user_id', [user_id])
            cursor.execute('INSERT INTO subscriptions (user_id, rs) VALUES (%s, %s) '
                           'ON DUPLICATE KEY UPDATE user_id=user_id', [user_id, rs])
            if cursor.rowcount == 1:
                return True
        return False

    def rm_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute('DELETE FROM subscriptions WHERE user_id=%s AND rs=%s', [user_id, rs])
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

    def migrate_from(self, old_manager: FileBasedSubscriptionManager):
        for subscriber in old_manager.get_subscribers():
            print(f"Migrate user_id {subscriber}")
            for subscription in old_manager.get_subscriptions(subscriber):
                print(f"Add subscription for {subscription}")
                self.add_subscription(int(subscriber), subscription)
                self.set_last_update(int(subscriber), old_manager.get_last_update())

    def set_last_update(self, user_id: int, date: datetime):
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE bot_user SET last_update=%s WHERE user_id=%s", [date, user_id])

    def get_last_update(self, user_id: int) -> Optional[datetime]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT last_update FROM bot_user WHERE user_id=%s", [user_id])
            row = cursor.fetchone()
            if row is not None and 'last_update' in row:
                return row['last_update']
