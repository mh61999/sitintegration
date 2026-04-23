"""Outbound pairing client for SIT tablets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import secrets
from typing import Awaitable, Callable

from aiohttp import ClientError, WSMsgType

try:
    from asyncio import timeout as async_timeout
except ImportError:  # pragma: no cover - compatibility fallback for older HA
    from async_timeout import timeout as async_timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    HMAC_ALGORITHM,
    MESSAGE_PAIRING_ACK,
    MESSAGE_PAIRING_HELLO,
    MESSAGE_PAIRING_RESPONSE,
    MESSAGE_PAIRING_TOKEN,
    PROTOCOL_VERSION,
    SIT_WS_PATH_TEMPLATE,
)

_LOGGER = logging.getLogger(__name__)

PAIRING_TIMEOUT = 20
CONNECT_TIMEOUT = 10


@dataclass(frozen=True)
class PairingResult:
    """Result of a successful pairing exchange."""

    device_id: str
    device_name: str
    auth_token: str


class PairingError(Exception):
    """Raised when the tablet pairing exchange fails."""

    def __init__(self, reason: str) -> None:
        """Initialize the pairing error."""
        super().__init__(reason)
        self.reason = reason


ApproveDeviceId = Callable[[str], Awaitable[None]]


async def async_pair_device(
    hass: HomeAssistant,
    *,
    host: str,
    port: int,
    path: str,
    pairing_code: str,
    requested_device_name: str | None,
    approve_device_id: ApproveDeviceId | None = None,
) -> PairingResult:
    """Pair with a temporary websocket hosted by the Android app."""
    session = async_get_clientsession(hass)
    url = _build_ws_url(host, port, path)
    auth_token = secrets.token_urlsafe(48)
    websocket = None

    try:
        async with async_timeout(PAIRING_TIMEOUT):
            websocket = await session.ws_connect(
                url,
                timeout=CONNECT_TIMEOUT,
                heartbeat=30,
            )

            await websocket.send_json(
                {
                    "type": MESSAGE_PAIRING_HELLO,
                    "protocol": PROTOCOL_VERSION,
                    "source": "home_assistant",
                    "pairing_code": pairing_code,
                    "requested_device_name": requested_device_name or "",
                }
            )

            response = await _receive_json(websocket)
            _validate_pairing_response(response, pairing_code)

            device_id = str(response.get("device_id", "")).strip()
            if not device_id:
                raise PairingError("missing_device_id")

            if approve_device_id is not None:
                await approve_device_id(device_id)

            device_name = (
                str(response.get("device_name") or requested_device_name or "").strip()
                or "SIT tablet"
            )

            await websocket.send_json(
                {
                    "type": MESSAGE_PAIRING_TOKEN,
                    "protocol": PROTOCOL_VERSION,
                    "device_id": device_id,
                    "device_name": device_name,
                    "auth_token": auth_token,
                    "ha_websocket_path": SIT_WS_PATH_TEMPLATE.format(
                        device_id=device_id
                    ),
                    "signature": {
                        "algorithm": HMAC_ALGORITHM,
                        "payload": "canonical JSON with sorted keys and no spaces",
                    },
                }
            )

            ack = await _receive_json(websocket)
            _validate_token_ack(ack, device_id)

            return PairingResult(
                device_id=device_id,
                device_name=device_name,
                auth_token=auth_token,
            )

    except PairingError:
        raise
    except (asyncio.TimeoutError, TimeoutError, ClientError, OSError) as err:
        _LOGGER.debug("Failed to pair with SIT tablet at %s: %s", url, err)
        raise PairingError("cannot_connect") from err
    finally:
        if websocket is not None and not websocket.closed:
            await websocket.close()


async def _receive_json(websocket) -> dict:
    """Receive one JSON websocket message."""
    message = await websocket.receive()

    if message.type == WSMsgType.TEXT:
        try:
            data = json.loads(message.data)
        except json.JSONDecodeError as err:
            raise PairingError("invalid_response") from err

        if not isinstance(data, dict):
            raise PairingError("invalid_response")
        return data

    if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
        raise PairingError("connection_closed")

    if message.type == WSMsgType.ERROR:
        raise PairingError("connection_closed")

    raise PairingError("invalid_response")


def _validate_pairing_response(response: dict, pairing_code: str) -> None:
    """Validate the tablet response to the HA hello message."""
    if response.get("type") != MESSAGE_PAIRING_RESPONSE:
        raise PairingError("invalid_response")
    if response.get("ok") is False:
        raise PairingError("invalid_pairing_code")

    returned_code = response.get("pairing_code")
    if returned_code is not None and str(returned_code) != pairing_code:
        raise PairingError("invalid_pairing_code")
    if response.get("ok") is not True and returned_code is None:
        raise PairingError("invalid_pairing_code")


def _validate_token_ack(ack: dict, device_id: str) -> None:
    """Validate that the app says it received and stored the token."""
    if ack.get("type") != MESSAGE_PAIRING_ACK:
        raise PairingError("token_not_confirmed")
    if ack.get("device_id") not in (None, device_id):
        raise PairingError("token_not_confirmed")
    if ack.get("token_received") is not True and ack.get("ok") is not True:
        raise PairingError("token_not_confirmed")


def _build_ws_url(host: str, port: int, path: str) -> str:
    """Build a websocket URL from the config flow input."""
    host = host.strip()
    path = path.strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"

    if host.startswith(("ws://", "wss://")):
        return f"{host.rstrip('/')}{path}"

    return f"ws://{host}:{port}{path}"
