"""Binary sensors for the Vehicle POC integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Vehicle POC binary sensors."""
    async_add_entities(
        [
            UnknownVehicleBinarySensor(),
            GuestDrivewayBinarySensor(),
            DeliveryBinarySensor(),
        ]
    )


class VehiclePocBinarySensor(BinarySensorEntity, RestoreEntity):
    """Base push binary sensor fed by the agent API."""

    _attr_should_poll = False

    def __init__(self, key: str, name: str, icon: str | None = None) -> None:
        self._attr_unique_id = f"vehicle_poc_{key}"
        self._attr_name = name
        if icon:
            self._attr_icon = icon
        self._attr_is_on = False
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"
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


class UnknownVehicleBinarySensor(VehiclePocBinarySensor):
    """On when an unidentified (non-fleet, non-delivery) vehicle is visible."""

    def __init__(self) -> None:
        super().__init__("unknown_vehicle", "Unknown Vehicle", icon="mdi:car-question")

    def _update_from_payload(self, payload: dict) -> None:
        self._attr_is_on = payload["unknown_vehicle"]


class GuestDrivewayBinarySensor(VehiclePocBinarySensor):
    """On when an unknown vehicle has lingered in the driveway (2+ scans)."""

    def __init__(self) -> None:
        super().__init__("guest_driveway", "Guest In Driveway", icon="mdi:account")

    def _update_from_payload(self, payload: dict) -> None:
        self._attr_is_on = payload["guest_driveway"]


class DeliveryBinarySensor(VehiclePocBinarySensor):
    """On when a delivery truck is present or a package is waiting."""

    def __init__(self) -> None:
        super().__init__("delivery", "Delivery Active", icon="mdi:truck-delivery")

    def _update_from_payload(self, payload: dict) -> None:
        delivery = payload["delivery"]
        self._attr_is_on = delivery["active"]
        self._attr_extra_state_attributes = {
            "delivery_truck": delivery["delivery_truck"],
            "truck_service": delivery["truck_service"],
            "package_on_porch": delivery["package_on_porch"],
            "package_in_driveway": delivery["package_in_driveway"],
            "last_delivery": delivery["last_delivery"],
        }
