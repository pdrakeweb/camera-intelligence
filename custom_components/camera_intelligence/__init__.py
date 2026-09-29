"""Camera Intelligence integration: agent-fed presence/state sensors."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_VEHICLES, DEFAULT_VEHICLES, DOMAIN, PLATFORMS
from .http import CameraIntelligenceStateView, CameraIntelligenceUpdateView

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_VEHICLES, default=DEFAULT_VEHICLES): vol.All(
                    cv.ensure_list, [cv.string]
                )
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Camera Intelligence integration.

    YAML configuration is imported into a config entry so both setup styles
    share the same code path.
    """
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=dict(config[DOMAIN]),
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Camera Intelligence from a config entry."""
    store = hass.data.setdefault(DOMAIN, {})
    store[CONF_VEHICLES] = entry.data.get(CONF_VEHICLES, DEFAULT_VEHICLES)
    store.setdefault("state", None)  # latest agent payload

    if not store.get("_views_registered"):
        hass.http.register_view(CameraIntelligenceUpdateView())
        hass.http.register_view(CameraIntelligenceStateView())
        store["_views_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    vehicles = store[CONF_VEHICLES]
    _LOGGER.info("Camera Intelligence set up for vehicles: %s", ", ".join(vehicles))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Camera Intelligence config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
