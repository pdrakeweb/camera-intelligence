"""Sensors for the Camera Intelligence integration.

Entity model: the entity is named for the thing ("Sportage"); the state
describes its status ("home"). Presence-style entities use home/away/unknown;
event-style entities use present/none or delivered/none.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_VEHICLES,
    DOMAIN,
    PACKAGE_NONE,
    PRESENCE_PRESENT,
    SIGNAL_UPDATE,
    STATUS_UNKNOWN,
)
from .presence_hints import (
    DRIVER_IDS,
    DRIVER_VEHICLES,
    KEY_TRACKERS,
    PERSONS,
    compute_hint,
    compute_person_hint,
    drivers_home,
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Camera Intelligence sensors (legacy YAML discovery path)."""
    async_add_entities(_build_entities(hass.data[DOMAIN]))


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Camera Intelligence sensors from a config entry."""
    async_add_entities(_build_entities(hass.data[DOMAIN]))


def _build_entities(store: dict) -> list[SensorEntity]:
    entities: list[CameraIntelligenceSensor] = [
        VehiclePresenceSensor(vehicle) for vehicle in store.get(CONF_VEHICLES, [])
    ]
    entities.extend(
        VehiclePresenceHintsSensor(vehicle)
        for vehicle in store.get(CONF_VEHICLES, [])
    )
    entities.extend(PersonPresenceHintsSensor(person_id) for person_id in DRIVER_IDS)
    entities.append(DriversHomeSensor())
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


class VehiclePresenceHintsSensor(SensorEntity):
    """Advisory Bayesian presence hint: likelihood the vehicle is home.

    Fuses non-camera evidence only (time of day, key trackers, family
    presence) via presence_hints.compute_hint. The name says "Hints" on
    purpose: the camera-based vehicle sensors remain the primary UI source
    of truth. Recomputes when this vehicle's key trackers change, plus a
    5-minute interval backstop (covers family-presence drift).
    """

    _attr_should_poll = False

    def __init__(self, vehicle: str) -> None:
        self._vehicle = vehicle
        key = f"{vehicle}_presence_hints"
        self._attr_unique_id = f"camera_intelligence_{key}"
        self._attr_name = f"{vehicle.replace('_', ' ').title()} Presence Hints"
        self._attr_icon = "mdi:gauge"
        self._attr_native_unit_of_measurement = "%"
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    def _watched_entities(self) -> list[str]:
        entities = list(KEY_TRACKERS.get(self._vehicle, []))
        for driver, _role in DRIVER_VEHICLES.get(self._vehicle, []):
            cfg = PERSONS[driver]
            entities.extend([cfg["person"], cfg["phone"]])
        return entities

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                self._watched_entities(),
                self._async_recompute,
            )
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_recompute, timedelta(minutes=5)
            )
        )
        self._recompute()

    @callback
    def _async_recompute(self, *args) -> None:
        self._recompute()

    def _recompute(self) -> None:
        probability, audit = compute_hint(self.hass, self._vehicle)
        self._attr_native_value = int(probability * 100)
        self._attr_extra_state_attributes = audit
        self.async_write_ha_state()


class PersonPresenceHintsSensor(SensorEntity):
    """Advisory Bayesian presence hint for one driver.

    Fuses person.<id> entity + that driver's phone tracker + time of day via
    presence_hints.compute_person_hint. Camera data NEVER enters here
    (circularity rule). Recomputes on the person/phone entity changes plus
    a 5-minute interval backstop.
    """

    _attr_should_poll = False

    def __init__(self, person_id: str) -> None:
        self._person_id = person_id
        name = PERSONS[person_id]["name"]
        key = f"person_{person_id}_presence_hints"
        self._attr_unique_id = f"camera_intelligence_{key}"
        self._attr_name = f"{name} Presence Hints"
        self._attr_icon = "mdi:account-question"
        self._attr_native_unit_of_measurement = "%"
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    def _watched_entities(self) -> list[str]:
        cfg = PERSONS[self._person_id]
        return [cfg["person"], cfg["phone"]]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                self._watched_entities(),
                self._async_recompute,
            )
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_recompute, timedelta(minutes=5)
            )
        )
        self._recompute()

    @callback
    def _async_recompute(self, *args) -> None:
        self._recompute()

    def _recompute(self) -> None:
        probability, audit = compute_person_hint(self.hass, self._person_id)
        self._attr_native_value = int(probability * 100)
        self._attr_extra_state_attributes = audit
        self.async_write_ha_state()


class DriversHomeSensor(SensorEntity):
    """Count of drivers currently likely home (person-hint >= 50%).

    Integer count with home/away name lists in attributes. Intended as the
    data source for a family dashboard card, replacing raw phone-presence.
    Recomputes on any driver person-entity change plus a 5-minute backstop.
    """

    _attr_should_poll = False

    def __init__(self) -> None:
        self._attr_unique_id = "camera_intelligence_drivers_home"
        self._attr_name = "Drivers Home"
        self._attr_icon = "mdi:account-group"
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    def _watched_entities(self) -> list[str]:
        return [PERSONS[pid]["person"] for pid in DRIVER_IDS]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                self._watched_entities(),
                self._async_recompute,
            )
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_recompute, timedelta(minutes=5)
            )
        )
        self._recompute()

    @callback
    def _async_recompute(self, *args) -> None:
        self._recompute()

    def _recompute(self) -> None:
        home_ids, away_ids, probs = drivers_home(self.hass)
        self._attr_native_value = len(home_ids)
        self._attr_extra_state_attributes = {
            "home": [PERSONS[pid]["name"] for pid in home_ids],
            "away": [PERSONS[pid]["name"] for pid in away_ids],
            "probabilities": {PERSONS[pid]["name"]: p for pid, p in probs.items()},
            "total_drivers": len(DRIVER_IDS),
            "advisory": True,
        }
        self.async_write_ha_state()


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
    """Single combined count: known visitors + unknown guests.

    The state is one number for the dashboard: the count of known visitors
    currently on the property, plus unknown guests (unidentified vehicles
    lingering in the driveway). Attributes break the count down and list
    who each entry is — named visitors and an "Unknown guest" entry when
    one is present. Packages are NOT included: they have their own
    dashboard button bound to the package sensor.

    The individual guest and package sensors remain for automations; this
    sensor is the combined display count.
    """

    def __init__(self) -> None:
        super().__init__("visitors", "Visitors", icon="mdi:account-group")
        self._attr_native_value = 0

    def _update_from_payload(self, payload: dict) -> None:
        visitors = payload.get("visitors") or []
        guest = payload.get("guest") or {}

        guest_present = guest.get("status") == PRESENCE_PRESENT

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
        }
        self._attr_native_value = len(visitors) + (1 if guest_present else 0)
        self._attr_extra_state_attributes = {
            "visitors": [v.get("name") for v in visitors],
            "details": details,
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
