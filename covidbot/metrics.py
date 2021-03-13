from prometheus_client.metrics import Counter, Gauge, Summary

RECV_MESSAGE_COUNT = Counter('bot_recv_message_count', 'Received messages')
SENT_MESSAGE_COUNT = Counter('bot_sent_message_count', 'Sent text messages')
SENT_IMAGES_COUNT = Counter('bot_sent_images_count', 'Sent images')
BOT_COMMAND_COUNT = Counter('bot_command_total', 'Received Bot Commands', ['command'])

BOT_RESPONSE_TIME = Summary('bot_response_time', 'Latency of requests')

# User statistics
USER_COUNT = Gauge('bot_total_user', 'Number of Bot users', ['platform'])
AVERAGE_SUBSCRIPTION_COUNT = Gauge('bot_avg_subscriptions', 'Average No. of subscriptions')

# Visualization related
CREATED_GRAPHS = Counter('bot_viz_created_graph_count', 'Number of created graphs', ['type'])
CACHED_GRAPHS = Counter('bot_viz_cached_graph_count', 'Number of created graphs', ['type'])

# Location Service
LOCATION_OSM_LOOKUP = Summary('bot_location_osm_lookup', 'Duration of OSM Requests')
LOCATION_GEO_LOOKUP = Summary('bot_location_geo_lookup', 'Time used for geolocation lookup')
LOCATION_DB_LOOKUP = Summary('bot_location_db_lookup', 'Time used for database lookup')

# Twitter Metrics
API_RATE_LIMIT = Gauge('bot_api_rate_limit', 'Current Rate Limit', ['platform', 'type'])
API_RESPONSE_CODE = Counter('bot_api_response_code', 'Twitter API response codes', ['platform', 'code'])
API_RESPONSE_TIME = Summary('bot_api_response_time', 'Twitter API response time', ['platform'])
