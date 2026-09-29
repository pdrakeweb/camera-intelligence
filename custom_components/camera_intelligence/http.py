"""Local HTTP API for the Camera Intelligence integration.

The integration is intentionally inference-backend-agnostic: it does not run
any vision model itself. An external agent (currently a scheduled worker that
classifies camera snapshots against a photo gallery) POSTs a full state
snapshot to /api/camera_intelligence/update, and the integration fans it out
to its sensor entities. Swap the agent for a Coral TPU pipeline, Frigate, or
anything else later without touching the entities.

Entity model: the entity is named for the thing ("Sportage"); the state
describes its status ("home"). Presence-style things use home/away/unknown;
event-style things use present/none or delivered/none.
"""

from __future__ import annotations

from http import HTTPStatus

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    API_STATE_PATH,
    API_UPDATE_PATH,
    DOMAIN,
    PACKAGE_DELIVERED,
    PACKAGE_NONE,
    PRESENCE_NONE,
    PRESENCE_PRESENT,
    SIGNAL_UPDATE,
    STATUS_AWAY,
    STATUS_HOME,
    STATUS_UNKNOWN,
    VALID_VEHICLE_STATUS,
)


def _norm_vehicle_status(value) -> str:
    """Coerce agent home/away values to home/away/unknown.

    Accepts booleans (legacy), None, and the canonical strings.
    """
    if isinstance(value, bool):
        return STATUS_HOME if value else STATUS_AWAY
    if value is None:
        return STATUS_UNKNOWN
    v = str(value).lower()
    return v if v in VALID_VEHICLE_STATUS else STATUS_UNKNOWN


def _norm_presence(value) -> str:
    if isinstance(value, bool):
        return PRESENCE_PRESENT if value else PRESENCE_NONE
    v = str(value).lower()
    return v if v in (PRESENCE_PRESENT, PRESENCE_NONE) else PRESENCE_NONE


def normalize_payload(data: dict) -> dict:
    """Coerce an agent payload into canonical shape (pure function)."""
    vehicles = {}
    for name, info in (data.get("vehicles") or {}).items():
        info = info or {}
        # Accept both {"status": "home"} and legacy {"home": true/false/null}.
        status = info.get("status", info.get("home", None))
        vehicles[str(name)] = {
            "status": _norm_vehicle_status(status),
            "last_seen": info.get("last_seen"),
            "last_camera": info.get("last_camera"),
        }

    guest = data.get("guest") or {}
    if "present" not in guest and "guest_driveway" in data:
        # Legacy flat key.
        guest = {"present": data["guest_driveway"]}

    package = data.get("package") or {}
    delivery = data.get("delivery") or {}
    if "delivered" not in package and delivery:
        # Legacy delivery block.
        package = {
            "delivered": delivery.get("active", False),
            "location": (
                "porch"
                if delivery.get("package_on_porch")
                else "driveway"
                if delivery.get("package_in_driveway")
                else ("driveway" if delivery.get("delivery_truck") else "none")
            ),
            "truck_service": delivery.get("truck_service") or "none",
            "last_delivery": delivery.get("last_delivery"),
        }

    delivered = bool(package.get("delivered", False))
    return {
        "vehicles": vehicles,
        "all_vehicles": _norm_vehicle_status(
            data.get("all_vehicles", data.get("all_home", None))
        ),
        "driveway_vehicles": [str(v) for v in (data.get("driveway_vehicles") or [])],
        "unknown_vehicle": _norm_presence(data.get("unknown_vehicle", False)),
        "guest": {
            "status": _norm_presence(guest.get("present", False)),
            "first_seen": guest.get("first_seen"),
            "camera": guest.get("camera"),
            "streak": guest.get("streak", 0),
        },
        "package": {
            "status": PACKAGE_DELIVERED if delivered else PACKAGE_NONE,
            "location": package.get("location") or "none",
            "truck_service": package.get("truck_service") or "none",
            "last_delivery": package.get("last_delivery"),
        },
    }


class CameraIntelligenceUpdateView(HomeAssistantView):
    """Accept a full presence/state snapshot from the agent."""

    url = API_UPDATE_PATH
    name = "api:camera_intelligence:update"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001 - malformed body
            return self.json(
                {"error": "invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST
            )
        if not isinstance(data, dict):
            return self.json(
                {"error": "payload must be a JSON object"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        payload = normalize_payload(data)
        hass.data[DOMAIN]["state"] = payload
        async_dispatcher_send(hass, SIGNAL_UPDATE)
        return self.json({"ok": True})


class CameraIntelligenceStateView(HomeAssistantView):
    """Return the last snapshot the agent pushed (debug/diagnostics)."""

    url = API_STATE_PATH
    name = "api:camera_intelligence:state"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        return self.json(hass.data[DOMAIN].get("state") or {})
