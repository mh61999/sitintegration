"""Config flow for the SIT tablet integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AUTH_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EXPOSED_ENTITIES,
    CONF_PAIRING_CODE,
    CONF_WS_PATH,
    DEFAULT_PAIRING_PORT,
    DEFAULT_PAIRING_WS_PATH,
    DOMAIN,
)
from .pairing import PairingError, async_pair_device

_LOGGER = logging.getLogger(__name__)


class SITConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SIT tablets."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return SITOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Pair a tablet and create a config entry."""
        if user_input is None:
            return self._show_user_form()

        exposed_entities = _normalize_entity_ids(
            user_input.get(CONF_EXPOSED_ENTITIES)
        )

        async def approve_device_id(device_id: str) -> None:
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

        try:
            pairing = await async_pair_device(
                self.hass,
                host=user_input[CONF_HOST].strip(),
                port=user_input[CONF_PORT],
                path=user_input[CONF_WS_PATH].strip(),
                pairing_code=user_input[CONF_PAIRING_CODE].strip(),
                requested_device_name=(user_input.get(CONF_DEVICE_NAME) or "").strip(),
                approve_device_id=approve_device_id,
            )
        except AbortFlow:
            return self._show_user_form(
                user_input=user_input,
                errors={"base": "already_configured"},
            )
        except PairingError as err:
            _LOGGER.debug("SIT pairing failed: %s", err)
            return self._show_user_form(
                user_input=user_input,
                errors={"base": err.reason},
            )

        title = pairing.device_name or user_input.get(CONF_DEVICE_NAME) or "SIT tablet"
        return self.async_create_entry(
            title=title,
            data={
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_PORT: user_input[CONF_PORT],
                CONF_WS_PATH: user_input[CONF_WS_PATH].strip(),
                CONF_DEVICE_ID: pairing.device_id,
                CONF_DEVICE_NAME: pairing.device_name,
                CONF_AUTH_TOKEN: pairing.auth_token,
            },
            options={CONF_EXPOSED_ENTITIES: exposed_entities},
        )

    def _show_user_form(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Show the pairing form."""
        user_input = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=user_input.get(CONF_HOST, ""),
                    ): str,
                    vol.Required(
                        CONF_PORT,
                        default=user_input.get(CONF_PORT, DEFAULT_PAIRING_PORT),
                    ): int,
                    vol.Required(
                        CONF_WS_PATH,
                        default=user_input.get(
                            CONF_WS_PATH,
                            DEFAULT_PAIRING_WS_PATH,
                        ),
                    ): str,
                    vol.Required(
                        CONF_PAIRING_CODE,
                        default=user_input.get(CONF_PAIRING_CODE, ""),
                    ): str,
                    vol.Optional(
                        CONF_DEVICE_NAME,
                        default=user_input.get(CONF_DEVICE_NAME, ""),
                    ): str,
                    vol.Optional(
                        CONF_EXPOSED_ENTITIES,
                        default=_normalize_entity_ids(
                            user_input.get(CONF_EXPOSED_ENTITIES)
                        ),
                    ): _entity_selector(self.hass),
                }
            ),
            errors=errors or {},
        )


class SITOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle SIT options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Update exposed entities."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_EXPOSED_ENTITIES: _normalize_entity_ids(
                        user_input.get(CONF_EXPOSED_ENTITIES)
                    )
                },
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXPOSED_ENTITIES,
                        default=_normalize_entity_ids(
                            self.config_entry.options.get(CONF_EXPOSED_ENTITIES)
                        ),
                    ): _entity_selector(self.hass)
                }
            ),
        )


def _entity_selector(hass) -> Any:
    """Return a multi-select validator for current HA entities."""
    options = {
        state.entity_id: f"{state.entity_id} ({state.state})"
        for state in sorted(
            hass.states.async_all(),
            key=lambda item: item.entity_id,
        )
    }
    return cv.multi_select(options)


def _normalize_entity_ids(value: Any) -> list[str]:
    """Normalize a form entity list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return sorted({str(item) for item in value if item})
