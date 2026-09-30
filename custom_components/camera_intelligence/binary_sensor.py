"""Per-zone package-presence binary sensors.

Drives per-camera dashboard visibility: a camera card can show itself when
its own drop zone has a package waiting, without showing every camera.
Zones come from the agent payload's package "zones" block (per-zone parcel
counts, e.g. {"porch": 0, "driveway": 1}).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SIGNAL_UPDATE

ZONES = ("porch", "driveway")


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up per-zone package binary sensors from a config entry."""
    async_add_entities(PackageZoneBinarySensor(zone) for zone in ZONES)


class PackageZoneBinarySensor(BinarySensorEntity, RestoreEntity):
    """on when at least one parcel is waiting in this drop zone."""

    _attr_should_poll = False

    def __init__(self, zone: str) -> None:
        self._zone = zone
        self._attr_unique_id = f"camera_intelligence_package_{zone}"
        self._attr_name = f"Package {zone.title()}"
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY
        self._attr_is_on = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            # Restore across restarts until the agent pushes again.
            self._attr_is_on = last.state == "on"
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update)
        )
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        payload = self.hass.data[DOMAIN].get("state")
        if payload:
            zones = (payload.get("package") or {}).get("zones") or {}
            try:
                count = int(zones.get(self._zone) or 0)
            except (TypeError, ValueError):
                count = 0
            self._attr_is_on = count > 0
            self.async_write_ha_state()
