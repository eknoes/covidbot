from typing import List, Optional

from psycopg2._psycopg import connection

from covidbot.file_based_subscription_manager import FileBasedSubscriptionManager


class SubscriptionManager(object):
    connection: connection

    def __init__(self, db_connection: connection):
        self.connection = db_connection
        self._create_db()

    def _create_db(self):
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions '
                               '(user_id INTEGER, rs INTEGER, added DATE DEFAULT now(), '
                               'UNIQUE(user_id, rs))')

    def add_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('INSERT INTO subscriptions (user_id, rs) VALUES (%s, %s) '
                               'ON CONFLICT DO NOTHING', [user_id, rs])
                if cursor.rowcount == 1:
                    return True
        return False

    def rm_subscription(self, user_id: int, rs: int) -> bool:
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM subscriptions WHERE user_id=%s AND rs=%s', [user_id, rs])
                if cursor.rowcount == 1:
                    return True
        return False

    def get_subscriptions(self, user_id: int) -> Optional[List[int]]:
        result = []
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT rs FROM subscriptions WHERE user_id=%s', [user_id])
                for row in cursor.fetchall():
                    result.append(row['rs'])
        return result

    def delete_user(self, user_id: int) -> bool:
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM subscriptions WHERE user_id=%s', [user_id])
                if cursor.rowcount > 0:
                    return True
        return False

    def get_all_user(self) -> List[int]:
        result = []
        with self.connection as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT DISTINCT user_id FROM subscriptions')
                for row in cursor.fetchall():
                    result.append(row['user_id'])
        return result

    def migrate_from(self, old_manager: FileBasedSubscriptionManager):
        for subscriber in old_manager.get_subscribers():
            print(f"Migrate user_id {subscriber}")
            for subscription in old_manager.get_subscriptions(subscriber):
                print(f"Add subscription for {subscription}")
                self.add_subscription(int(subscriber), subscription)


