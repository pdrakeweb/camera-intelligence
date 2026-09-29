# Vehicle POC for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

A Home Assistant custom integration that receives vision-based vehicle
identification snapshots from an external agent and exposes them as proper
entities with state restore across restarts.

The inference backend is intentionally external and agnostic: a camera agent
classifies snapshots against a photo gallery of the household fleet and
delivery liveries, then pushes one complete state snapshot per update. This
integration owns the entity registry entries, so states survive HA restarts
(no more `unknown` after every reboot, unlike raw `/api/states` writes).

**This integration will set up the following platforms.**

Platform | Description
-- | --
`sensor` | Per-vehicle home/away, all-home rollup, driveway vehicle list
`binary_sensor` | Unknown vehicle, guest in driveway, delivery active

## Quick Start

### Step 1: Install the Integration

**Prerequisites:** This integration requires [HACS](https://hacs.xyz/) to be installed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pdrakeweb&repository=vehicle-poc&category=integration)

Or add it manually: HACS -> Integrations -> (menu) Custom repositories ->
paste `https://github.com/pdrakeweb/vehicle-poc`, category Integration ->
Download, then restart Home Assistant.

<details>
<summary>Manual Installation (Advanced)</summary>

1. Download the `custom_components/vehicle_poc/` folder from this repository
2. Copy it to your Home Assistant `custom_components/` directory
3. Restart Home Assistant

</details>

### Step 2: Configure

Add to `configuration.yaml`:

```yaml
vehicle_poc:
```

Restart Home Assistant. The integration registers its local API and entities
on setup.

### Step 3: Push state from your agent

The agent sends one complete snapshot per update:

```
POST /api/vehicle_poc/update   (authenticated, local only)
```

```json
{
  "vehicles": {
    "sportage":  {"home": true,  "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.barn_fluent"},
    "sorento":   {"home": true,  "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.barn_fluent_2"},
    "entourage": {"home": true,  "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.driveway_circle_fluent_lens_0"},
    "sky":       {"home": true,  "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.barn_fluent"},
    "qx80":      {"home": null},
    "commander": {"home": null}
  },
  "driveway_vehicles": ["2007 Hyundai Entourage"],
  "unknown_vehicle": false,
  "guest_driveway": false,
  "delivery": {
    "active": false,
    "truck_service": "none",
    "package_on_porch": false,
    "package_in_driveway": false,
    "last_delivery": null
  }
}
```

Read back the last pushed snapshot any time:

```
GET /api/vehicle_poc/state
```

## Entities

- `sensor.vehicle_poc_<vehicle>_home` — `on` / `off` / `unknown` per fleet vehicle
- `sensor.vehicle_poc_all_home` — rollup across the fleet
- `sensor.vehicle_poc_driveway_vehicles` — comma-separated list, or `none`
- `binary_sensor.vehicle_poc_unknown_vehicle` — unidentified vehicle visible now
- `binary_sensor.vehicle_poc_guest_driveway` — unknown vehicle persisting in driveway
- `binary_sensor.vehicle_poc_delivery` — delivery truck or latched package active

All entities use stable unique IDs and restore their last state across
Home Assistant restarts.

## Notes

- The integration never classifies images itself; it is a state sink for an
  external vision agent. Gallery matching policy (no zero-shot guesses,
  delivery liveries classified separately) lives in the agent, not here.
- `vehicle_poc:` in `configuration.yaml` currently takes no options; the
  vehicle list is derived from each pushed payload.

[releases-shield]: https://img.shields.io/github/release/pdrakeweb/vehicle-poc.svg
[releases]: https://github.com/pdrakeweb/vehicle-poc/releases
[license-shield]: https://img.shields.io/github/license/pdrakeweb/vehicle-poc.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
