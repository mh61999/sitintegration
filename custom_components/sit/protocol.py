"""Shared SIT websocket protocol helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_payload(payload: dict[str, Any]) -> bytes:
    """Return the canonical JSON bytes used for HMAC signing."""
    return json.dumps(
        payload,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sign_payload(token: str, payload: dict[str, Any]) -> str:
    """Sign a payload with the shared device token."""
    return hmac.new(
        token.encode("utf-8"),
        canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()


def compare_signature(token: str, payload: dict[str, Any], signature: str) -> bool:
    """Return True when a provided signature matches the payload."""
    expected = sign_payload(token, payload)
    return hmac.compare_digest(expected, signature)


def signed_envelope(
    token: str,
    message_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Wrap a payload in a signed websocket envelope."""
    safe_payload = _json_safe(payload)
    return {
        "type": message_type,
        "payload": safe_payload,
        "signature": sign_payload(token, safe_payload),
    }


def state_to_payload(state) -> dict[str, Any]:
    """Serialize a Home Assistant state for the tablet."""
    context = getattr(state, "context", None)
    payload = {
        "entity_id": state.entity_id,
        "state": state.state,
        "attributes": state.attributes,
        "last_changed": state.last_changed.isoformat(),
        "last_updated": state.last_updated.isoformat(),
    }

    if context is not None:
        payload["context"] = _drop_none_values(
            {
                "id": getattr(context, "id", None),
                "parent_id": getattr(context, "parent_id", None),
                "user_id": getattr(context, "user_id", None),
            }
        )

    return _json_safe(_drop_none_values(payload))


def _drop_none_values(value: Any) -> Any:
    """Remove None values from nested protocol data before signing."""
    if isinstance(value, dict):
        return {
            key: _drop_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_none_values(item) for item in value]
    return value


def _json_safe(value: Any) -> Any:
    """Convert Home Assistant values to JSON-safe data."""
    return json.loads(json.dumps(value, default=str))
