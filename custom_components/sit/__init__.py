"""SIT tablet integration for Home Assistant."""

from __future__ import annotations

from collections import deque
import logging
from types import SimpleNamespace
from typing import Any

from aiohttp import WSMsgType, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.helpers.event import async_track_state_change_event
except ImportError:  # pragma: no cover - compatibility fallback for older HA
    async_track_state_change_event = None
    from homeassistant.helpers.event import async_track_state_change
else:
    async_track_state_change = None

try:
    from homeassistant.helpers import device_registry as dr
except ImportError:  # pragma: no cover - compatibility fallback for older HA
    dr = None

from .const import (
    CONF_AUTH_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EXPOSED_ENTITIES,
    DATA_VIEW_REGISTERED,
    DOMAIN,
    MESSAGE_ACTION_RESULT,
    MESSAGE_AUTH,
    MESSAGE_AUTH_OK,
    MESSAGE_ENTITY_REMOVED,
    MESSAGE_ENTITY_SNAPSHOT,
    MESSAGE_ENTITY_UPDATE,
    MESSAGE_ERROR,
    MESSAGE_PING,
    MESSAGE_PONG,
    MESSAGE_SERVICE_CALL,
    PROTOCOL_VERSION,
    SIT_WS_URL,
)
from .protocol import compare_signature, signed_envelope, state_to_payload

_LOGGER = logging.getLogger(__name__)

MAX_NONCES = 500


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the SIT integration."""
    hass.data.setdefault(DOMAIN, {})
    _async_register_view(hass)
    return True


def _async_register_view(hass: HomeAssistant) -> None:
    """Register the websocket view once."""
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get(DATA_VIEW_REGISTERED):
        return

    if not hasattr(hass, "http"):
        _LOGGER.debug("HTTP integration is not ready; SIT websocket not registered")
        return

    hass.http.register_view(SITWebSocketView())
    hass.data[DOMAIN][DATA_VIEW_REGISTERED] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a paired SIT tablet."""
    _async_register_view(hass)

    runtime = SITRuntime(hass, entry)
    await runtime.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_register_device(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a paired SIT tablet."""
    runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if isinstance(runtime, SITRuntime):
        await runtime.async_stop()
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Reload a SIT config entry."""
    await async_unload_entry(hass, entry)
    return await async_setup_entry(hass, entry)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the runtime when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the tablet in the Home Assistant device registry."""
    if dr is None:
        return

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
        manufacturer="SIT",
        model="Android tablet",
        name=entry.data.get(CONF_DEVICE_NAME) or entry.title,
    )


class SITRuntime:
    """Runtime state for one paired tablet."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize runtime state."""
        self.hass = hass
        self.entry = entry
        self.clients: set[Any] = set()
        self._seen_nonces: deque[str] = deque(maxlen=MAX_NONCES)
        self._seen_nonce_set: set[str] = set()
        self._unsub_state = None

    @property
    def device_id(self) -> str:
        """Return the paired tablet id."""
        return self.entry.data[CONF_DEVICE_ID]

    @property
    def token(self) -> str:
        """Return the HMAC token for this tablet."""
        return self.entry.data[CONF_AUTH_TOKEN]

    @property
    def exposed_entities(self) -> tuple[str, ...]:
        """Return the entity ids exposed to this tablet."""
        return tuple(self.entry.options.get(CONF_EXPOSED_ENTITIES, ()))

    async def async_start(self) -> None:
        """Start listening for state changes."""
        entity_ids = self.exposed_entities
        if not entity_ids:
            return

        self._unsub_state = _track_state_changes(
            self.hass,
            entity_ids,
            self._async_state_changed,
        )

    async def async_stop(self) -> None:
        """Stop runtime work and close open websocket clients."""
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

        clients = list(self.clients)
        self.clients.clear()
        for client in clients:
            await client.close()

    def remember_nonce(self, nonce: str) -> bool:
        """Return False if the nonce was already used."""
        if nonce in self._seen_nonce_set:
            return False

        if len(self._seen_nonces) == self._seen_nonces.maxlen:
            old_nonce = self._seen_nonces.popleft()
            self._seen_nonce_set.discard(old_nonce)

        self._seen_nonces.append(nonce)
        self._seen_nonce_set.add(nonce)
        return True

    def verify_envelope(self, message: dict[str, Any]) -> dict[str, Any]:
        """Validate an incoming signed message and return its payload."""
        payload = message.get("payload")
        signature = message.get("signature")

        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if not isinstance(signature, str):
            raise ValueError("signature is required")
        if not compare_signature(self.token, payload, signature):
            raise ValueError("invalid signature")

        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise ValueError("payload nonce is required")
        if not self.remember_nonce(nonce):
            raise ValueError("payload nonce was already used")

        return payload

    async def async_send(
        self,
        websocket: web.WebSocketResponse,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Send a signed message to one connected tablet websocket."""
        await websocket.send_json(signed_envelope(self.token, message_type, payload))

    async def async_broadcast(
        self,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Send a signed message to all connected tablet websockets."""
        for websocket in list(self.clients):
            if websocket.closed:
                self.clients.discard(websocket)
                continue
            try:
                await self.async_send(websocket, message_type, payload)
            except ConnectionError:
                self.clients.discard(websocket)

    async def async_send_snapshot(self, websocket: web.WebSocketResponse) -> None:
        """Send the current state for all exposed entities."""
        entities = []
        for entity_id in self.exposed_entities:
            state = self.hass.states.get(entity_id)
            if state is not None:
                entities.append(state_to_payload(state))

        await self.async_send(
            websocket,
            MESSAGE_ENTITY_SNAPSHOT,
            {
                "protocol": PROTOCOL_VERSION,
                "device_id": self.device_id,
                "entities": entities,
            },
        )

    @callback
    def _async_state_changed(self, event) -> None:
        """Schedule a state update for connected tablets."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        if old_state is not None and new_state is not None:
            if old_state.state == new_state.state:
                return

        if new_state is None:
            payload = {"entity_id": event.data["entity_id"]}
            self.hass.async_create_task(
                self.async_broadcast(MESSAGE_ENTITY_REMOVED, payload)
            )
            return

        payload = {
            "entity": state_to_payload(new_state),
            "old_state": old_state.state if old_state is not None else None,
        }
        self.hass.async_create_task(
            self.async_broadcast(MESSAGE_ENTITY_UPDATE, payload)
        )


class SITWebSocketView(HomeAssistantView):
    """Unauthenticated HTTP view protected by per-device HMAC messages."""

    url = SIT_WS_URL
    name = "api:sit:websocket"
    requires_auth = False

    async def get(
        self,
        request: web.Request,
        device_id: str,
    ) -> web.WebSocketResponse:
        """Handle a tablet websocket session."""
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)

        hass = request.app["hass"]
        runtime = _runtime_for_device_id(hass, device_id)
        if runtime is None:
            await websocket.send_json(
                {
                    "type": MESSAGE_ERROR,
                    "payload": {
                        "code": "unknown_device",
                        "message": "Unknown SIT device id",
                    },
                }
            )
            await websocket.close()
            return websocket

        authenticated = False

        try:
            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    incoming = message.json()
                    if not isinstance(incoming, dict):
                        raise ValueError("message must be a JSON object")

                    authenticated = await _async_handle_text_message(
                        runtime,
                        websocket,
                        incoming,
                        authenticated,
                    )
                    continue

                if message.type == WSMsgType.ERROR:
                    _LOGGER.debug(
                        "SIT websocket error for %s: %s",
                        runtime.device_id,
                        websocket.exception(),
                    )
                    break
        except ValueError as err:
            await runtime.async_send(
                websocket,
                MESSAGE_ERROR,
                {"code": "bad_message", "message": str(err)},
            )
        finally:
            runtime.clients.discard(websocket)

        return websocket


async def _async_handle_text_message(
    runtime: SITRuntime,
    websocket: web.WebSocketResponse,
    message: dict[str, Any],
    authenticated: bool,
) -> bool:
    """Process one tablet websocket message."""
    message_type = message.get("type")

    if message_type == MESSAGE_PING:
        await runtime.async_send(websocket, MESSAGE_PONG, {"ok": True})
        return authenticated

    if message_type == MESSAGE_AUTH:
        payload = runtime.verify_envelope(message)
        if payload.get(CONF_DEVICE_ID) not in (None, runtime.device_id):
            raise ValueError("auth payload device_id does not match websocket URL")

        runtime.clients.add(websocket)
        await runtime.async_send(
            websocket,
            MESSAGE_AUTH_OK,
            {
                "protocol": PROTOCOL_VERSION,
                "device_id": runtime.device_id,
                "exposed_entities": list(runtime.exposed_entities),
            },
        )
        await runtime.async_send_snapshot(websocket)
        return True

    if not authenticated:
        raise ValueError("auth is required before other messages")

    if message_type == MESSAGE_SERVICE_CALL:
        payload = runtime.verify_envelope(message)
        try:
            await _async_handle_service_call(runtime, payload)
        except PermissionError as err:
            await runtime.async_send(
                websocket,
                MESSAGE_ACTION_RESULT,
                {
                    "ok": False,
                    "nonce": payload["nonce"],
                    "error": "not_allowed",
                    "message": str(err),
                },
            )
            return True
        except (ValueError, HomeAssistantError) as err:
            await runtime.async_send(
                websocket,
                MESSAGE_ACTION_RESULT,
                {
                    "ok": False,
                    "nonce": payload["nonce"],
                    "error": "service_call_failed",
                    "message": str(err),
                },
            )
            return True

        await runtime.async_send(
            websocket,
            MESSAGE_ACTION_RESULT,
            {
                "ok": True,
                "nonce": payload["nonce"],
            },
        )
        return True

    raise ValueError(f"unsupported message type: {message_type}")


async def _async_handle_service_call(
    runtime: SITRuntime,
    payload: dict[str, Any],
) -> None:
    """Call a Home Assistant service for exposed entities only."""
    service = payload.get("service")
    if not isinstance(service, str) or not service:
        raise ValueError("service is required")

    entity_ids = _extract_entity_ids(payload)
    if not entity_ids:
        raise ValueError("at least one entity_id is required")

    exposed_entities = set(runtime.exposed_entities)
    unknown_entities = sorted(entity_ids - exposed_entities)
    if unknown_entities:
        raise PermissionError(
            f"service call contains unexposed entities: {', '.join(unknown_entities)}"
        )

    domains = {entity_id.split(".", 1)[0] for entity_id in entity_ids}
    domain = payload.get("domain")
    if domain is None:
        if len(domains) != 1:
            raise ValueError("domain is required when multiple domains are targeted")
        domain = next(iter(domains))

    if not isinstance(domain, str) or not domain:
        raise ValueError("domain is required")
    if domain not in domains:
        raise PermissionError("service domain must match the exposed entity domain")

    service_data = dict(payload.get("service_data") or {})
    service_data.pop("entity_id", None)
    target = {"entity_id": sorted(entity_ids)}

    try:
        await runtime.hass.services.async_call(
            domain,
            service,
            service_data=service_data,
            target=target,
            blocking=True,
        )
    except TypeError:
        service_data["entity_id"] = sorted(entity_ids)
        await runtime.hass.services.async_call(
            domain,
            service,
            service_data,
            blocking=True,
        )
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError(str(err)) from err


def _extract_entity_ids(payload: dict[str, Any]) -> set[str]:
    """Extract entity ids from a service-call payload."""
    entity_ids = set()
    entity_ids.update(_coerce_entity_ids(payload.get("entity_id")))

    target = payload.get("target")
    if isinstance(target, dict):
        entity_ids.update(_coerce_entity_ids(target.get("entity_id")))

    service_data = payload.get("service_data")
    if isinstance(service_data, dict):
        entity_ids.update(_coerce_entity_ids(service_data.get("entity_id")))

    return entity_ids


def _coerce_entity_ids(value: Any) -> set[str]:
    """Coerce an entity_id value to a set."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if item}
    return set()


def _runtime_for_device_id(
    hass: HomeAssistant,
    device_id: str,
) -> SITRuntime | None:
    """Return the runtime for a paired device id."""
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, SITRuntime) and value.device_id == device_id:
            return value
    return None


def _track_state_changes(hass: HomeAssistant, entity_ids, action):
    """Track state changes using whichever HA helper is available."""
    if async_track_state_change_event is not None:
        return async_track_state_change_event(hass, list(entity_ids), action)

    def _legacy_state_changed(entity_id, old_state, new_state):
        action(
            SimpleNamespace(
                data={
                    "entity_id": entity_id,
                    "old_state": old_state,
                    "new_state": new_state,
                }
            )
        )

    return async_track_state_change(hass, list(entity_ids), _legacy_state_changed)
