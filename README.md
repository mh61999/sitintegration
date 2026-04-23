# SIT Integration

Custom Home Assistant integration for pairing an Android tablet app over a temporary tablet-hosted websocket, then moving to a Home Assistant-hosted websocket for entity sync and signed actions.

## Install

Copy `custom_components/sit` from this folder into your Home Assistant `custom_components` directory, restart Home Assistant, then add **SIT Integration** from the integrations UI.

The Home Assistant integration domain is `sit`. The folder around it is named `SIT integration` because Home Assistant domains cannot contain spaces.

## Pairing protocol

The Android app opens a temporary websocket and displays a pairing code. In Home Assistant, enter the tablet IP, websocket port, websocket path, pairing code, and the entities to expose.

Home Assistant connects to the tablet websocket and sends:

```json
{
  "type": "sit_pairing_hello",
  "protocol": 1,
  "source": "home_assistant",
  "pairing_code": "123456",
  "requested_device_name": "Kitchen tablet"
}
```

The app should answer:

```json
{
  "type": "sit_pairing_response",
  "ok": true,
  "pairing_code": "123456",
  "device_id": "android-device-id",
  "device_name": "Kitchen tablet"
}
```

Home Assistant generates a lifetime token and sends:

```json
{
  "type": "sit_pairing_token",
  "protocol": 1,
  "device_id": "android-device-id",
  "device_name": "Kitchen tablet",
  "auth_token": "generated-token",
  "ha_websocket_path": "/api/sit/ws/android-device-id",
  "signature": {
    "algorithm": "HMAC-SHA256",
    "payload": "canonical JSON with sorted keys and no spaces"
  }
}
```

The app confirms storage:

```json
{
  "type": "sit_pairing_ack",
  "ok": true,
  "token_received": true,
  "device_id": "android-device-id"
}
```

Home Assistant then closes the pairing websocket. The app can stop hosting its temporary websocket and connect to Home Assistant at `/api/sit/ws/{device_id}`.

## Runtime websocket

Incoming app messages use signed envelopes:

```json
{
  "type": "auth",
  "payload": {
    "device_id": "android-device-id",
    "nonce": "unique-value"
  },
  "signature": "hex-hmac"
}
```

The signature is `HMAC-SHA256(auth_token, canonical_json(payload))`, where canonical JSON uses sorted keys and no whitespace separators.

After auth, Home Assistant sends `auth_ok`, then `entity_snapshot` containing all currently exposed entity states. Later it sends `entity_update` only when the entity state string changes, plus `entity_removed` if an exposed entity disappears.

To control an exposed entity, the app sends a signed `service_call` message:

```json
{
  "type": "service_call",
  "payload": {
    "nonce": "unique-action-id",
    "domain": "light",
    "service": "turn_on",
    "target": {
      "entity_id": "light.kitchen"
    },
    "service_data": {
      "brightness_pct": 60
    }
  },
  "signature": "hex-hmac"
}
```

The integration only allows service calls targeting entities selected in the config flow or options flow. It does not pass through area or device targets from the app.

