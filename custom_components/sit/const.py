"""Constants for the SIT tablet integration."""

DOMAIN = "sit"
PLATFORMS = ["button"]

PROTOCOL_VERSION = 1

CONF_AUTH_TOKEN = "auth_token"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_EXPOSED_ENTITIES = "exposed_entities"
CONF_PAIRING_CODE = "pairing_code"
CONF_WS_PATH = "websocket_path"

DEFAULT_PAIRING_PORT = 8765
DEFAULT_PAIRING_WS_PATH = "/"

DATA_VIEW_REGISTERED = "_websocket_view_registered"
DATA_SERVICE_REGISTERED = "_service_registered"

SIT_WS_URL = "/api/sit/ws/{device_id}"
SIT_WS_PATH_TEMPLATE = "/api/sit/ws/{device_id}"

MESSAGE_ACTION_RESULT = "action_result"
MESSAGE_AUTH = "auth"
MESSAGE_AUTH_OK = "auth_ok"
MESSAGE_ENTITY_REMOVED = "entity_removed"
MESSAGE_ENTITY_SNAPSHOT = "entity_snapshot"
MESSAGE_ENTITY_UPDATE = "entity_update"
MESSAGE_ERROR = "error"
MESSAGE_PAIRING_ACK = "sit_pairing_ack"
MESSAGE_PAIRING_HELLO = "sit_pairing_hello"
MESSAGE_PAIRING_RESPONSE = "sit_pairing_response"
MESSAGE_PAIRING_TOKEN = "sit_pairing_token"
MESSAGE_PING = "ping"
MESSAGE_PONG = "pong"
MESSAGE_SERVICE_CALL = "service_call"
MESSAGE_SETUP = "setup"

HMAC_ALGORITHM = "HMAC-SHA256"

SERVICE_SEND_SETUP = "send_setup"
