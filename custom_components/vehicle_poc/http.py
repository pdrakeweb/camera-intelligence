"""Local HTTP API for the Vehicle POC integration.

The integration is intentionally inference-backend-agnostic: it does not run
any vision model itself. An external agent (currently a scheduled worker that
classifies camera snapshots against a photo gallery) POSTs a full state
snapshot to /api/vehicle_poc/update, and the integration fans it out to its
sensor and binary_sensor entities. Swap the agent for a Coral TPU pipeline,
Frigate, or anything else later without touching the entities.
"""

from __future__ import annotations

from http import HTTPStatus

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import API_STATE_PATH, API_UPDATE_PATH, DOMAIN, SIGNAL_UPDATE

VALID_HOME = {"on", "off", "unknown"}


def _norm_home(value) -> str:
    """Coerce agent home/away values to on/off/unknown."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "unknown"
    v = str(value).lower()
    return v if v in VALID_HOME else "unknown"


def normalize_payload(data: dict) -> dict:
    """Coerce an agent payload into canonical shape (pure function)."""
    vehicles = {}
    for name, info in (data.get("vehicles") or {}).items():
        info = info or {}
        vehicles[str(name)] = {
            "home": _norm_home(info.get("home")),
            "last_seen": info.get("last_seen"),
            "last_camera": info.get("last_camera"),
        }
    delivery = data.get("delivery") or {}
    return {
        "vehicles": vehicles,
        "all_home": _norm_home(data.get("all_home")),
        "driveway_vehicles": [str(v) for v in (data.get("driveway_vehicles") or [])],
        "unknown_vehicle": bool(data.get("unknown_vehicle", False)),
        "guest_driveway": bool(data.get("guest_driveway", False)),
        "delivery": {
            "active": bool(delivery.get("active", False)),
            "delivery_truck": bool(delivery.get("delivery_truck", False)),
            "truck_service": delivery.get("truck_service") or "none",
            "package_on_porch": bool(delivery.get("package_on_porch", False)),
            "package_in_driveway": bool(delivery.get("package_in_driveway", False)),
            "last_delivery": delivery.get("last_delivery"),
        },
    }


class VehiclePocUpdateView(HomeAssistantView):
    """Accept a full vehicle/delivery state snapshot from the agent."""

    url = API_UPDATE_PATH
    name = "api:vehicle_poc:update"
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


class VehiclePocStateView(HomeAssistantView):
    """Return the last snapshot the agent pushed (debug/diagnostics)."""

    url = API_STATE_PATH
    name = "api:vehicle_poc:state"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        return self.json(hass.data[DOMAIN].get("state") or {})
