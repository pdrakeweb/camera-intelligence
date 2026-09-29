"""Sensors for the Vehicle POC integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_VEHICLES, DOMAIN, SIGNAL_UPDATE


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Vehicle POC sensors."""
    store = hass.data[DOMAIN]
    entities: list[VehiclePocSensor] = [
        VehicleHomeSensor(vehicle) for vehicle in store.get(CONF_VEHICLES, [])
    ]
    entities.append(AllHomeSensor())
    entities.append(DrivewayVehiclesSensor())
    async_add_entities(entities)


class VehiclePocSensor(SensorEntity, RestoreEntity):
    """Base push sensor fed by the agent API."""

    _attr_should_poll = False

    def __init__(self, key: str, name: str, icon: str | None = None) -> None:
        self._key = key
        self._attr_unique_id = f"vehicle_poc_{key}"
        self._attr_name = name
        if icon:
            self._attr_icon = icon
        self._attr_native_value = "unknown"
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            # Restore across restarts until the agent pushes again.
            self._attr_native_value = last.state
            self._attr_extra_state_attributes = dict(last.attributes or {})
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update)
        )
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        payload = self.hass.data[DOMAIN].get("state")
        if payload:
            self._update_from_payload(payload)
            self.async_write_ha_state()

    def _update_from_payload(self, payload: dict) -> None:
        raise NotImplementedError


class VehicleHomeSensor(VehiclePocSensor):
    """Per-vehicle home/away sensor."""

    def __init__(self, vehicle: str) -> None:
        super().__init__(
            f"{vehicle}_home",
            f"{vehicle.replace('_', ' ').title()} Home",
            icon="mdi:car",
        )
        self._vehicle = vehicle

    def _update_from_payload(self, payload: dict) -> None:
        info = payload["vehicles"].get(self._vehicle)
        if info is None:
            return
        self._attr_native_value = info["home"]
        self._attr_extra_state_attributes = {
            "last_seen": info.get("last_seen"),
            "last_camera": info.get("last_camera"),
        }


class AllHomeSensor(VehiclePocSensor):
    """Aggregate: on when every tracked vehicle is home."""

    def __init__(self) -> None:
        super().__init__("all_home", "All Vehicles Home", icon="mdi:garage")

    def _update_from_payload(self, payload: dict) -> None:
        self._attr_native_value = payload["all_home"]


class DrivewayVehiclesSensor(VehiclePocSensor):
    """Comma-separated list of vehicles currently in the driveway."""

    def __init__(self) -> None:
        super().__init__(
            "driveway_vehicles", "Driveway Vehicles", icon="mdi:car-multiple"
        )

    def _update_from_payload(self, payload: dict) -> None:
        vehicles = payload["driveway_vehicles"]
        self._attr_native_value = ", ".join(vehicles) if vehicles else "none"
