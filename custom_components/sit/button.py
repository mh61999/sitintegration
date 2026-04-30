"""Button entities for the SIT tablet integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SIT button entities for one config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SITOpenSetupButton(entry, runtime)])


class SITOpenSetupButton(ButtonEntity):
    """Button that asks the paired tablet to return to setup mode."""

    _attr_has_entity_name = True
    _attr_name = "Open setup"
    _attr_icon = "mdi:cog-refresh-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, runtime) -> None:
        """Initialize the button."""
        self._entry = entry
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_open_setup"

    @property
    def device_info(self):
        """Return device information for this button."""
        return {
            "identifiers": {(DOMAIN, self._entry.data[CONF_DEVICE_ID])},
            "manufacturer": "SIT",
            "model": "Android tablet",
            "name": self._entry.data.get(CONF_DEVICE_NAME) or self._entry.title,
        }

    async def async_press(self) -> None:
        """Send the setup command to the connected tablet."""
        await self._runtime.async_send_setup_command()
