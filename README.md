# SIT Integration

Custom Home Assistant integration for pairing an Android tablet app over a temporary tablet-hosted websocket, then moving to a Home Assistant-hosted websocket for entity sync and signed actions.

## Install

### HACS

1. Open HACS in Home Assistant.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/mh61999/sitintegration` as an **Integration** repository.
4. Install **SIT Integration**.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services**, add **SIT Integration**, and pair the tablet.

### Manual

Copy `custom_components/sit` from this repository into your Home Assistant `custom_components` directory, restart Home Assistant, then add **SIT Integration** from the integrations UI.

The Home Assistant integration domain is `sit`.

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
  "ha_local_ip": "192.168.1.10",
  "ha_base_url": "http://homeassistant.local:8123",
  "ha_websocket_url": "ws://192.168.1.10:8123/api/sit/ws/android-device-id",
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

If `ha_websocket_url` is present in the token message, the Android app should use it directly. If it is missing, the app can combine the Home Assistant host it inferred during pairing with `ha_websocket_path`.

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
