# Camera Intelligence for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

A Home Assistant custom integration that receives vision-based observations
from an external camera agent and exposes them as proper entities with state
restore across restarts.

The inference backend is intentionally external and agnostic: a camera agent
classifies snapshots (vehicles against a photo gallery of the household fleet
and delivery liveries today; animals, people, and more tomorrow), then pushes
one complete state snapshot per update. This integration owns the entity
registry entries, so states survive HA restarts (no more `unknown` after
every reboot, unlike raw `/api/states` writes).

Entity model: the entity is named for the thing ("Sportage"); the state
describes its status ("home"). Presence-style entities use `home` / `away` /
`unknown`; event-style entities use `present` / `none` or `delivered` /
`none`. This is deliberately *not* `device_tracker` — that platform forces a
`source_type` (gps/router/bluetooth) and our source is camera vision.

**This integration will set up the following platforms.**

Platform | Description
-- | --
`sensor` | Per-vehicle presence, fleet rollup, driveway list, unknown vehicle, guest, package

## Quick Start

### Step 1: Install the Integration

**Prerequisites:** This integration requires [HACS](https://hacs.xyz/) to be installed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pdrakeweb&repository=camera-intelligence&category=integration)

Or add it manually: HACS -> Integrations -> (menu) Custom repositories ->
paste `https://github.com/pdrakeweb/camera-intelligence`, category Integration ->
Download, then restart Home Assistant.

<details>
<summary>Manual Installation (Advanced)</summary>

1. Download the `custom_components/camera_intelligence/` folder from this repository
2. Copy it to your Home Assistant `custom_components/` directory
3. Restart Home Assistant

</details>

### Step 2: Configure

No YAML needed. In Home Assistant go to Settings → Devices & services →
Add integration → **Camera Intelligence**, and confirm. The integration
registers its local API and entities on setup.

<details>
<summary>YAML configuration (legacy, optional)</summary>

```yaml
camera_intelligence:
```

A YAML entry is imported automatically into the UI configuration on the
next restart; you can remove the YAML afterwards.

</details>

### Step 3: Push state from your agent

The agent sends one complete snapshot per update:

```
POST /api/camera_intelligence/update   (authenticated, local only)
```

```json
{
  "vehicles": {
    "sportage":  {"status": "home", "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.barn_fluent"},
    "sorento":   {"status": "home", "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.barn_fluent_2"},
    "entourage": {"status": "home", "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.driveway_circle_fluent_lens_0"},
    "sky":       {"status": "home", "last_seen": "2026-09-29T17:20:37Z", "last_camera": "camera.barn_fluent"},
    "qx80":      {"status": "unknown"},
    "commander": {"status": "unknown"}
  },
  "all_vehicles": "unknown",
  "driveway_vehicles": ["2007 Hyundai Entourage"],
  "unknown_vehicle": false,
  "guest": {"present": false, "first_seen": null, "camera": null, "streak": 0},
  "visitors": [
    {"name": "Nana and Papa", "vehicle": "silver sedan", "last_seen": "2026-09-29T21:08:34Z", "last_camera": "camera.driveway_fluent_2"}
  ],
  "package": {"delivered": false, "location": "none", "truck_service": "none", "last_delivery": null}
}
```

Read back the last pushed snapshot any time:

```
GET /api/camera_intelligence/state
```

## Entities

- `sensor.camera_intelligence_<vehicle>` — "Sportage", `home` / `away` / `unknown` (attributes: last_seen, last_camera)
- `sensor.camera_intelligence_all_vehicles` — "All Vehicles", `home` / `away` / `unknown`
- `sensor.camera_intelligence_driveway_vehicles` — "Driveway Vehicles", comma-separated list or `none`
- `sensor.camera_intelligence_unknown_vehicle` — "Unknown Vehicle", `present` / `none` (single-scan)
- `sensor.camera_intelligence_guest` — "Guest", `present` / `none` (attributes: first_seen, camera, streak)
- `sensor.camera_intelligence_visitors` — "Visitors", single combined count: known visitors on the property + unknown guests (attributes: visitors, details — named visitors plus an "Unknown guest" entry when one is present, breakdown)
- `sensor.camera_intelligence_package` — "Package", `delivered` / `none` (attributes: package_count, zones, location, truck_service, last_delivery)
- `sensor.camera_intelligence_<vehicle>_presence_hints` — "Sorento Presence Hints", advisory 0–100% likelihood the vehicle is home (attributes: prior, time bucket, per-evidence contributions, audit). Fuses **non-camera evidence only** via Bayesian log-odds: time of day, key trackers, and driver-aware evidence (each mapped driver's person-hint probability, weighted primary 1.5 / secondary 0.6, plus a weak generic drivers-home-count lean). Camera classifications never feed it, so the vision agent can safely consume it as a prior without double-counting. The camera-based presence sensors above remain the primary UI source of truth.
- `sensor.peter_presence_hints` (likewise kelly/abby/julia/sarah) — "Peter Presence Hints", advisory 0–100% likelihood the driver is home. Fuses **person entity + phone tracker + time of day only** (night 23:00–05:00 prior 0.95, else 0.75). person.<id> is the primary observation; the phone is secondary because cell presence alone is not 100% accurate. Away readings weigh more than home readings (a phone on a charger falsely reads "home"). peter_jr is excluded (non-driver).
- `sensor.drivers_home` — "Drivers Home", integer count of drivers whose person-hint ≥ 50% (attributes: home/away name lists, per-driver probabilities, total). Intended data source for the family dashboard card, replacing raw phone presence.

All entities use stable unique IDs and restore their last state across
Home Assistant restarts.

## Circularity rule

- Person hints ← person entity / phone tracker / time of day ONLY.
- Vehicle hints ← key trackers / person hints / drivers-home count / time of day ONLY.
- Camera classifications feed NEITHER. The vision agent may consume vehicle
  hints as priors; visual evidence enters exactly once, in the classifier.
- Driver→vehicle mapping (Pete, Oct 6 2026): sky←peter; sportage←peter+abby;
  entourage←abby; qx80←sarah; sorento←kelly+sarah; commander←julia
  (primary listed first).

## Notes

- The integration never classifies images itself; it is a state sink for an
  external vision agent. Gallery matching policy (no zero-shot guesses,
  delivery liveries classified separately) lives in the agent, not here.
- `camera_intelligence:` in `configuration.yaml` currently takes no options
  beyond the vehicle list; the vehicle list is derived from each pushed
  payload when not configured.

[releases-shield]: https://img.shields.io/github/release/pdrakeweb/camera-intelligence.svg
[releases]: https://github.com/pdrakeweb/camera-intelligence/releases
[license-shield]: https://img.shields.io/github/license/pdrakeweb/camera-intelligence.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
