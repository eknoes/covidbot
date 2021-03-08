from prometheus_client.metrics import Counter

RECV_MESSAGE_COUNT = Counter('bot_recv_message_count', 'Received messages')
SENT_MESSAGE_COUNT = Counter('bot_sent_message_count', 'Sent text messages')
SENT_IMAGES_COUNT = Counter('bot_sent_images_count', 'Sent images')

BOT_COMMAND_COUNT = Counter('bot_command_total', 'Received Bot Commands', ['command'])

OSM_REQUEST_COUNT = Counter('bot_osm_requests_total', 'Total OSM Queries')
