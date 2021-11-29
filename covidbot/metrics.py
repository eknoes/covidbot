import logging
from sqlite3 import OperationalError

from mysql.connector import MySQLConnection
from prometheus_client.metrics import Counter, Gauge, Summary

RECV_MESSAGE_COUNT = Counter('bot_recv_message_count', 'Received messages')
SENT_MESSAGE_COUNT = Counter('bot_sent_message_count', 'Sent text messages')
FAILED_MESSAGE_COUNT = Counter('bot_failed_message_count',
                               'Number of messages failed to send')
SENT_IMAGES_COUNT = Counter('bot_sent_images_count', 'Sent images')
BOT_COMMAND_COUNT = Counter('bot_command_total', 'Received Bot Commands', ['command'])

BOT_RESPONSE_TIME = Summary('bot_response_time', 'Latency of requests')

# SingleCommand
DISCARDED_MESSAGE_COUNT = Counter('bot_discard_message_count',
                                  'Received but discarded messages')
SINGLE_COMMAND_RESPONSE_TIME = Summary('bot_response_time_single',
                                       'Response time to single command input')

# User statistics
USER_COUNT = Gauge('bot_total_user', 'Number of Bot users', ['platform'])
AVERAGE_SUBSCRIPTION_COUNT = Gauge('bot_avg_subscriptions',
                                   'Average No. of subscriptions')

# Report statistics
REPORTS_AVAILABLE = Gauge('bot_reports_available',
                          'Number of reports that need to be sent', ['platform'])

# Visualization related
CREATED_GRAPHS = Counter('bot_viz_created_graph_count', 'Number of created graphs',
                         ['type'])
CACHED_GRAPHS = Counter('bot_viz_cached_graph_count', 'Number of created graphs',
                        ['type'])

# Location Service
LOCATION_OSM_LOOKUP = Summary('bot_location_osm_lookup', 'Duration of OSM Requests')
LOCATION_GEO_LOOKUP = Summary('bot_location_geo_lookup',
                              'Time used for geolocation lookup')
LOCATION_DB_LOOKUP = Summary('bot_location_db_lookup', 'Time used for database lookup')

# Twitter Metrics
API_RATE_LIMIT = Gauge('bot_api_rate_limit', 'Current Rate Limit', ['platform', 'type'])
API_RESPONSE_CODE = Counter('bot_api_response_code', 'Twitter API response codes',
                            ['platform', 'code'])
API_RESPONSE_TIME = Summary('bot_api_response_time', 'Twitter API response time',
                            ['platform'])
API_ERROR = Counter('bot_api_connection_error', 'Twitter API connection error')

# Error Metrics
BOT_SEND_MESSAGE_ERRORS = Counter('bot_send_message_error',
                                  'Number of errors while sending a message',
                                  ['platform', 'error'])


class MonitorMetrics:
    connection: MySQLConnection

    def __init__(self, connection: MySQLConnection):
        self.connection = connection
        self.log = logging.getLogger(__name__)

    def get_social_network_user_number(self, name: str) -> int:
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    'SELECT followers FROM platform_statistics WHERE platform=%s LIMIT 1',
                    [name])
                rows = cursor.fetchall()
                if rows:
                    return rows[0]['followers']
                return 0
        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_social_network_user_number(name)

    def get_user_number(self, name: str) -> int:
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    "SELECT COUNT(user_id) as user_num FROM bot_user WHERE platform=%s AND activated=1",
                    [name])
                row = cursor.fetchone()
                if row and 'user_num' in row and row['user_num']:
                    return row['user_num']
                return 0
        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_user_number(name)

    def get_unsent_reports_number(self, platform: str) -> int:
        num = 0
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                last_updates = {'cases-germany': None, 'icu-germany': None,
                                'vaccinations-germany': None}

                cursor.execute(
                    "SELECT MAX(last_update) as updated FROM covid_data WHERE rs=0")
                last_updates['cases-germany'] = cursor.fetchone()['updated']

                cursor.execute(
                    "SELECT MAX(last_update) as updated FROM covid_vaccinations WHERE district_id=0")
                last_updates['vaccinations-germany'] = cursor.fetchone()['updated']

                cursor.execute(
                    "SELECT MAX(updated) as updated FROM icu_beds WHERE district_id=0")
                last_updates['icu-germany'] = cursor.fetchone()['updated']

                cursor.execute("""SELECT bot_user.user_id, rs.report as report, sr.sent_report as sent, bus.value as weekly FROM bot_user
    JOIN report_subscriptions rs on bot_user.user_id = rs.user_id
    LEFT JOIN bot_user_sent_reports sr on bot_user.user_id = sr.user_id AND rs.report = sr.report
    LEFT JOIN bot_user_settings bus on bot_user.user_id = bus.user_id AND bus.setting = "report_weekly"
WHERE activated=1 AND platform=%s AND (sr.sent_report = (SELECT MAX(sent_report) FROM bot_user_sent_reports
      WHERE user_id = bot_user.user_id AND report = rs.report) OR sr.sent_report IS NULL)""", [platform])

                for row in cursor.fetchall():
                    if last_updates[row['report']] is None:
                        continue

                    if row['sent'] is None or row['sent'] < last_updates[row['report']]:
                        if row['weekly'] and last_updates[row['report']].weekday() != 0:
                            continue
                        num += 1

                cursor.execute("""SELECT COUNT(id) as unsent_messages FROM user_responses
JOIN bot_user bu on bu.user_id = user_responses.receiver_id AND bu.platform=%s AND activated=1
WHERE sent IS NULL""", [platform])
                return num + cursor.fetchone()['unsent_messages']

        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_unsent_reports_number(platform)

    def get_average_subscriptions(self) -> float:
        try:
            with self.connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    "SELECT COUNT(*)/COUNT(DISTINCT user_id) as mean FROM subscriptions ORDER BY user_id "
                    "LIMIT 1")
                row = cursor.fetchone()

                if row['mean']:
                    return row['mean']
                return 1.0
        except OperationalError as e:
            self.log.exception(f"OperationalError: {e.msg}", exc_info=e)
            self.connection.reconnect()
            return self.get_average_subscriptions()
