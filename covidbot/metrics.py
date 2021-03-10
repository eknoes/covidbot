from prometheus_client.metrics import Counter, Gauge, Summary

RECV_MESSAGE_COUNT = Counter('bot_recv_message_count', 'Received messages')
SENT_MESSAGE_COUNT = Counter('bot_sent_message_count', 'Sent text messages')
SENT_IMAGES_COUNT = Counter('bot_sent_images_count', 'Sent images')
BOT_COMMAND_COUNT = Counter('bot_command_total', 'Received Bot Commands', ['command'])

BOT_RESPONSE_TIME = Summary('bot_response_time', 'Latency of requests')

# User statistics
TOTAL_USER_COUNT = Gauge('bot_total_user', 'Number of Bot users')
AVERAGE_SUBSCRIPTION_COUNT = Gauge('bot_avg_subscriptions', 'Average No. of subscriptions')

# Visualization related
CREATED_GRAPHS = Counter('bot_viz_created_graph_count', 'Number of created graphs', ['type'])
CACHED_GRAPHS = Counter('bot_viz_cached_graph_count', 'Number of created graphs', ['type'])

# Location Service
OSM_REQUEST_COUNT = Counter('bot_osm_requests_total', 'Total OSM Queries')
OSM_REQUEST_TIME = Summary('bot_osm_request_time', 'Duration of OSM Requests')
GEOLOCATION_LOOKUP_COUNT = Counter('bot_location_geo_count', 'Total queries by geolocation')
GEOLOCATION_LOOKUP_TIME = Summary('bot_location_geo_time', 'Time used for geolocation lookup')