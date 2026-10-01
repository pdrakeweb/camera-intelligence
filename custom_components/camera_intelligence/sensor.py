"""Sensors for the Camera Intelligence integration.

Entity model: the entity is named for the thing ("Sportage"); the state
describes its status ("home"). Presence-style entities use home/away/unknown;
event-style entities use present/none or delivered/none.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_VEHICLES,
    DOMAIN,
    PACKAGE_NONE,
    PRESENCE_PRESENT,
    SIGNAL_UPDATE,
    STATUS_UNKNOWN,
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Camera Intelligence sensors (legacy YAML discovery path)."""
    async_add_entities(_build_entities(hass.data[DOMAIN]))


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Camera Intelligence sensors from a config entry."""
    async_add_entities(_build_entities(hass.data[DOMAIN]))


def _build_entities(store: dict) -> list[CameraIntelligenceSensor]:
    entities: list[CameraIntelligenceSensor] = [
        VehiclePresenceSensor(vehicle) for vehicle in store.get(CONF_VEHICLES, [])
    ]
    entities.append(AllVehiclesSensor())
    entities.append(DrivewayVehiclesSensor())
    entities.append(UnknownVehicleSensor())
    entities.append(GuestSensor())
    entities.append(VisitorsSensor())
    entities.append(PackageSensor())
    return entities


class CameraIntelligenceSensor(SensorEntity, RestoreEntity):
    """Base push sensor fed by the agent API."""

    _attr_should_poll = False

    def __init__(self, key: str, name: str, icon: str | None = None) -> None:
        self._key = key
        self._attr_unique_id = f"camera_intelligence_{key}"
        self._attr_name = name
        if icon:
            self._attr_icon = icon
        self._attr_native_value = STATUS_UNKNOWN
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


class VehiclePresenceSensor(CameraIntelligenceSensor):
    """Per-vehicle presence: home / away / unknown."""

    def __init__(self, vehicle: str) -> None:
        super().__init__(
            vehicle,
            vehicle.replace("_", " ").title(),
            icon="mdi:car",
        )
        self._vehicle = vehicle

    def _update_from_payload(self, payload: dict) -> None:
        info = payload["vehicles"].get(self._vehicle)
        if info is None:
            return
        self._attr_native_value = info["status"]
        self._attr_extra_state_attributes = {
            "last_seen": info.get("last_seen"),
            "last_camera": info.get("last_camera"),
        }


class AllVehiclesSensor(CameraIntelligenceSensor):
    """Aggregate presence across the tracked fleet: home / away / unknown."""

    def __init__(self) -> None:
        super().__init__("all_vehicles", "All Vehicles", icon="mdi:garage")

    def _update_from_payload(self, payload: dict) -> None:
        self._attr_native_value = payload["all_vehicles"]


class DrivewayVehiclesSensor(CameraIntelligenceSensor):
    """Comma-separated list of vehicles currently in the driveway."""

    def __init__(self) -> None:
        super().__init__(
            "driveway_vehicles", "Driveway Vehicles", icon="mdi:car-multiple"
        )
        self._attr_native_value = "none"

    def _update_from_payload(self, payload: dict) -> None:
        vehicles = payload["driveway_vehicles"]
        self._attr_native_value = ", ".join(vehicles) if vehicles else "none"


class UnknownVehicleSensor(CameraIntelligenceSensor):
    """present when an unidentified vehicle is visible (single-scan)."""

    def __init__(self) -> None:
        super().__init__(
            "unknown_vehicle", "Unknown Vehicle", icon="mdi:car-question"
        )
        self._attr_native_value = "none"

    def _update_from_payload(self, payload: dict) -> None:
        self._attr_native_value = payload["unknown_vehicle"]


class GuestSensor(CameraIntelligenceSensor):
    """present when an unknown vehicle/person is lingering (guest)."""

    def __init__(self) -> None:
        super().__init__("guest", "Guest", icon="mdi:account")
        self._attr_native_value = "none"

    def _update_from_payload(self, payload: dict) -> None:
        guest = payload["guest"]
        self._attr_native_value = guest["status"]
        self._attr_extra_state_attributes = {
            "first_seen": guest.get("first_seen"),
            "camera": guest.get("camera"),
            "streak": guest.get("streak", 0),
        }


class VisitorsSensor(CameraIntelligenceSensor):
    """Single combined count: known visitors + unknown guests + packages.

    The state is one number for the dashboard: the count of known visitors
    currently on the property, plus unknown guests (unidentified vehicles
    lingering in the driveway), plus parcels awaiting pickup. Attributes
    break the count down and list who each entry is — named visitors and
    an "Unknown guest" entry when one is present.

    The individual guest and package sensors remain for automations; this
    sensor is the combined display count.
    """

    def __init__(self) -> None:
        super().__init__("visitors", "Visitors", icon="mdi:account-group")
        self._attr_native_value = 0

    def _update_from_payload(self, payload: dict) -> None:
        visitors = payload.get("visitors") or []
        guest = payload.get("guest") or {}
        package = payload.get("package") or {}

        guest_present = guest.get("status") == PRESENCE_PRESENT
        try:
            package_count = max(0, int(package.get("count") or 0))
        except (TypeError, ValueError):
            package_count = 0

        details = list(visitors)
        if guest_present:
            details.append(
                {
                    "name": "Unknown guest",
                    "vehicle": "unknown vehicle",
                    "first_seen": guest.get("first_seen"),
                    "last_camera": guest.get("camera"),
                    "streak": guest.get("streak", 0),
                }
            )

        breakdown = {
            "visitors": len(visitors),
            "guests": 1 if guest_present else 0,
            "packages": package_count,
        }
        self._attr_native_value = len(visitors) + (1 if guest_present else 0) + package_count
        self._attr_extra_state_attributes = {
            "visitors": [v.get("name") for v in visitors],
            "details": details,
            "package_count": package_count,
            "zones": package.get("zones") or {"porch": 0, "driveway": 0},
            "breakdown": breakdown,
        }


class PackageSensor(CameraIntelligenceSensor):
    """delivered when a delivery truck was seen or a package is waiting.

    Extra attributes: package_count (parcels outside awaiting pickup),
    location, truck_service, last_delivery.
    """

    def __init__(self) -> None:
        super().__init__("package", "Package", icon="mdi:package-variant")
        self._attr_native_value = PACKAGE_NONE

    def _update_from_payload(self, payload: dict) -> None:
        package = payload["package"]
        self._attr_native_value = package["status"]
        self._attr_extra_state_attributes = {
            "package_count": package.get("count", 0),
            "zones": package.get("zones") or {"porch": 0, "driveway": 0},
            "location": package.get("location"),
            "truck_service": package.get("truck_service"),
            "last_delivery": package.get("last_delivery"),
        }
