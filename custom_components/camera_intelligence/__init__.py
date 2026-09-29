"""Camera Intelligence integration: agent-fed presence/state sensors."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery

from .const import CONF_VEHICLES, DEFAULT_VEHICLES, DOMAIN
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
    """Set up the Camera Intelligence integration from YAML."""
    conf = config.get(DOMAIN, {})
    vehicles = conf.get(CONF_VEHICLES, DEFAULT_VEHICLES)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][CONF_VEHICLES] = vehicles
    hass.data[DOMAIN]["state"] = None  # latest agent payload

    hass.http.register_view(CameraIntelligenceUpdateView())
    hass.http.register_view(CameraIntelligenceStateView())

    hass.async_create_task(
        discovery.async_load_platform(hass, "sensor", DOMAIN, {}, conf)
    )

    _LOGGER.info("Camera Intelligence set up for vehicles: %s", ", ".join(vehicles))
    return True
