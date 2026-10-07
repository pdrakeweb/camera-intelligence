"""Bayesian "presence hints" for the Camera Intelligence integration.

Advisory-only likelihoods fused from NON-CAMERA evidence.

CIRCULARITY RULE (Pete, Oct 6 2026): camera classifications must NEVER feed
these sensors.
  person hints  <- person entity / phone tracker / time of day ONLY.
  vehicle hints <- key trackers / person hints / drivers-home count /
                   time of day ONLY.
The camera classifier MAY consume vehicle hints as priors — visual evidence
enters exactly once, in the classifier. Name these entities as hints so they
read as advisory, never as authoritative state.

Evidence hierarchy (Pete, Oct 6 2026):
  keys dominate > driver presence > time-of-day prior > generic count (weak).
Both keys home is a very strong home signal regardless of driver presence;
keys away is strong but never conclusive (keys occasionally land in a purse).
Person-away with keys home is WEAK evidence (may have caught a ride).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

try:  # pragma: no cover - exercised only inside Home Assistant
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - plain-python test path
    dt_util = None

_LOGGER = logging.getLogger(__name__)

# Verified live Oct 6 2026. entity_id -> vehicle mapping of Tile key trackers.
KEY_TRACKERS: dict[str, list[str]] = {
    "sorento": ["device_tracker.sorento_gray_key", "device_tracker.sorento_black_key"],
    "sportage": ["device_tracker.sportage_key_1", "device_tracker.sportage_key_2"],
    "qx80": ["device_tracker.qx80_key_1", "device_tracker.qx80_key_2"],
    "commander": ["device_tracker.jeep_key_1", "device_tracker.jeep_key_2"],
    "entourage": ["device_tracker.van_keys"],
    "sky": [],  # no key trackers; keys contribute nothing
}

# Per-driver person/phone mapping. Verified live Oct 6 2026.
# Drivers only: peter, kelly, abby, julia, sarah. peter_jr excluded (14).
PERSONS: dict[str, dict[str, str]] = {
    "peter": {"name": "Peter", "person": "person.peter",
              "phone": "device_tracker.pixel_10_pro_2"},
    "kelly": {"name": "Kelly", "person": "person.kelly",
              "phone": "device_tracker.kelly_s_pixel_8"},
    "abby": {"name": "Abby", "person": "person.abby",
             "phone": "device_tracker.abby_s_pixel_8"},
    "julia": {"name": "Julia", "person": "person.julia",
              "phone": "device_tracker.julia_s_pixel_8_pro"},
    "sarah": {"name": "Sarah", "person": "person.sarah",
              "phone": "device_tracker.sarah_s_pixel_9"},
}
DRIVER_IDS = ["peter", "kelly", "abby", "julia", "sarah"]

# Driver -> vehicle mapping (Pete, Oct 6 2026). Primary driver first.
DRIVER_VEHICLES: dict[str, list[tuple[str, str]]] = {
    "sky": [("peter", "primary")],
    "sportage": [("peter", "primary"), ("abby", "secondary")],
    "entourage": [("abby", "primary")],
    "qx80": [("sarah", "primary")],
    "sorento": [("kelly", "primary"), ("sarah", "secondary")],
    "commander": [("julia", "primary")],
}

STATE_HOME = "home"
STATE_AWAY = "not_home"

# Log-odds weights. Note: both-away is -4.5 (not the -3.0 first sketched) so
# that keys-away actually dominates the strong night prior in logit space:
# night (logit 3.48) - 4.5 ~= -1.0 -> ~26% before driver evidence,
# "low but never near the 1% clamp floor".
W_BOTH_KEYS_HOME = 3.0
W_ONE_KEY_AWAY = -1.0
W_BOTH_KEYS_AWAY = -4.5
W_SINGLE_KEY_HOME = 1.5
W_SINGLE_KEY_AWAY = -1.5
# Person-hint weights (log-odds). person.<id> is the primary observation;
# the phone tracker is secondary (cell presence alone is not 100% accurate).
# NOTE (deviation from first sketch, Oct 6 2026): away weights are stronger
# than home weights on purpose. A phone sitting on a charger falsely reads
# "home" (weak evidence), while a phone reading "away" almost always traveled
# with someone (strong evidence). Symmetric weights left a both-agreeing-away
# night case at ~61% — too high to be useful on a family dashboard.
W_PERSON_HOME = 1.5
W_PERSON_AWAY = -2.0
W_PHONE_HOME = 1.0
W_PHONE_AWAY = -1.5

# Driver evidence in vehicle hints: contribution = weight * (2p - 1), where p
# is the driver's person-hint probability. Primary drivers move the needle;
# secondary drivers are a gentle lean.
W_DRIVER_PRIMARY = 1.5
W_DRIVER_SECONDARY = 0.6
# Generic drivers-home count: deliberately weak so it never double-counts
# the driver-specific signals above.
W_DRIVERS_HOME_COUNT = 0.3

# Person-hint time-of-day priors (HA local time). People are home at night
# far more reliably than vehicles are.
PERSON_PRIOR_NIGHT = 0.95  # 23:00-05:00
PERSON_PRIOR_DAY = 0.75

# Per-person prior overrides (Pete, Oct 6 2026). Julia lives away at school
# (Grove City, PA) except holidays/breaks/summer, so her base rate is
# "away" — without this the night prior would wrongly insist she's home
# most nights. The override REPLACES the time-of-day prior for her.
# When she is home, person+phone evidence (+2.5 log-odds) still flips the
# sensor: logit(0.2)+2.5 ~= 1.1 -> ~75%.
PERSON_PRIOR_OVERRIDE: dict[str, float] = {
    "julia": 0.20,
}

# Time-of-day priors (HA local time).
PRIOR_NIGHT = 0.97  # 22:00-06:00
PRIOR_WORKDAY = 0.70  # weekday 09:00-17:00
PRIOR_OTHER = 0.85


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _time_bucket(now: datetime) -> tuple[str, float]:
    hour = now.hour
    if hour >= 22 or hour < 6:
        return "night", PRIOR_NIGHT
    if now.weekday() < 5 and 9 <= hour < 17:
        return "weekday_day", PRIOR_WORKDAY
    return "other", PRIOR_OTHER


def _state_of(hass, entity_id: str) -> str | None:
    """Return the entity state, or None when missing/unavailable/unknown."""
    try:
        state = hass.states.get(entity_id)
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug("presence_hints: error reading %s", entity_id)
        return None
    if state is None:
        return None
    s = state.state
    if s in ("unavailable", "unknown", None):
        return None
    return s


def _key_evidence(hass, vehicle: str) -> tuple[float, dict]:
    """Log-odds contribution from this vehicle's key trackers."""
    trackers = KEY_TRACKERS.get(vehicle, [])
    states = {}
    for entity_id in trackers:
        s = _state_of(hass, entity_id)
        states[entity_id] = s if s is not None else "missing"
    known = [s for s in states.values() if s != "missing"]
    if not known:
        return 0.0, {"states": states, "weight": 0.0, "note": "no key data"}

    if len(known) >= 2:
        away = sum(1 for s in known if s == STATE_AWAY)
        home = sum(1 for s in known if s == STATE_HOME)
        if away == 0 and home > 0:
            return W_BOTH_KEYS_HOME, {"states": states, "weight": W_BOTH_KEYS_HOME,
                                      "note": "both keys home"}
        if home == 0 and away > 0:
            return W_BOTH_KEYS_AWAY, {"states": states, "weight": W_BOTH_KEYS_AWAY,
                                      "note": "both keys away"}
        return W_ONE_KEY_AWAY, {"states": states, "weight": W_ONE_KEY_AWAY,
                                "note": "one key away"}
    # Single key tracker (e.g. entourage van_keys).
    s = known[0]
    if s == STATE_HOME:
        return W_SINGLE_KEY_HOME, {"states": states, "weight": W_SINGLE_KEY_HOME,
                                   "note": "key home"}
    if s == STATE_AWAY:
        return W_SINGLE_KEY_AWAY, {"states": states, "weight": W_SINGLE_KEY_AWAY,
                                   "note": "key away"}
    return 0.0, {"states": states, "weight": 0.0, "note": "key state not home/away"}


def _person_time_bucket(now: datetime) -> tuple[str, float]:
    hour = now.hour
    if hour >= 23 or hour < 5:
        return "night", PERSON_PRIOR_NIGHT
    return "day", PERSON_PRIOR_DAY


def compute_person_hint(
    hass, person_id: str, now: datetime | None = None
) -> tuple[float, dict]:
    """Bayesian log-odds fusion for one driver's likelihood of being home.

    Evidence: person.<id> entity + that driver's phone tracker + time of day.
    Camera data NEVER enters here (circularity rule). Missing entities
    contribute 0 and never raise.
    """
    if now is None:
        now = dt_util.now() if dt_util is not None else datetime.now().astimezone()

    cfg = PERSONS.get(person_id)
    if cfg is None:
        bucket, prior = _person_time_bucket(now)
        probability = min(0.98, max(0.02, prior))
        return probability, {
            "person": person_id, "note": "unknown person id; prior only",
            "probability": round(probability, 4),
        }

    bucket, prior = _person_time_bucket(now)
    if person_id in PERSON_PRIOR_OVERRIDE:
        prior = PERSON_PRIOR_OVERRIDE[person_id]
        bucket = f"{bucket}+away-base-rate"
    total = _logit(prior)
    evidence = []

    s = _state_of(hass, cfg["person"])
    if s == STATE_HOME:
        total += W_PERSON_HOME
        evidence.append({"source": "person_entity", "entity": cfg["person"],
                         "state": s, "weight": W_PERSON_HOME})
    elif s == STATE_AWAY:
        total += W_PERSON_AWAY
        evidence.append({"source": "person_entity", "entity": cfg["person"],
                         "state": s, "weight": W_PERSON_AWAY})
    else:
        evidence.append({"source": "person_entity", "entity": cfg["person"],
                         "state": s, "weight": 0.0, "note": "missing"})

    s = _state_of(hass, cfg["phone"])
    if s == STATE_HOME:
        total += W_PHONE_HOME
        evidence.append({"source": "phone", "entity": cfg["phone"],
                         "state": s, "weight": W_PHONE_HOME})
    elif s == STATE_AWAY:
        total += W_PHONE_AWAY
        evidence.append({"source": "phone", "entity": cfg["phone"],
                         "state": s, "weight": W_PHONE_AWAY})
    else:
        evidence.append({"source": "phone", "entity": cfg["phone"],
                         "state": s, "weight": 0.0, "note": "missing"})

    probability = min(0.98, max(0.02, _sigmoid(total)))
    audit = {
        "person": person_id,
        "name": cfg["name"],
        "local_time": now.isoformat(timespec="minutes"),
        "time_bucket": bucket,
        "prior": round(prior, 3),
        "evidence": evidence,
        "total_log_odds": round(total, 3),
        "probability": round(probability, 4),
        "advisory": True,
        "note": "Hint only — not authoritative presence. Phone presence "
                "alone is not 100% accurate.",
    }
    return probability, audit


def drivers_home(
    hass, now: datetime | None = None
) -> tuple[list[str], list[str], dict[str, float]]:
    """Split drivers into home/away by person-hint >= 0.5.

    Returns (home_ids, away_ids, probabilities). Used by the Drivers Home
    count sensor and as a weak generic observation in vehicle hints.
    """
    if now is None:
        now = dt_util.now() if dt_util is not None else datetime.now().astimezone()
    home, away, probs = [], [], {}
    for person_id in DRIVER_IDS:
        p, _ = compute_person_hint(hass, person_id, now)
        probs[person_id] = round(p, 4)
        (home if p >= 0.5 else away).append(person_id)
    return home, away, probs


def _driver_evidence(
    hass, vehicle: str, now: datetime
) -> tuple[float, dict]:
    """Driver-aware evidence for a vehicle hint.

    Driver-specific: each mapped driver's person-hint probability p
    contributes weight*(2p-1) (primary 1.5, secondary 0.6). Generic: the
    drivers-home count leans away when drivers are out, kept deliberately
    weak (0.3 per missing driver) so it never double-counts the
    driver-specific signals.
    """
    total = 0.0
    details: list[dict] = []

    for driver, role in DRIVER_VEHICLES.get(vehicle, []):
        p, _ = compute_person_hint(hass, driver, now)
        w = W_DRIVER_PRIMARY if role == "primary" else W_DRIVER_SECONDARY
        contrib = w * (2 * p - 1)
        total += contrib
        details.append({"driver": driver, "role": role,
                        "person_hint": round(p, 4),
                        "weight": w, "contribution": round(contrib, 3)})

    home_ids, away_ids, _ = drivers_home(hass, now)
    count_term = (len(home_ids) - len(DRIVER_IDS)) * W_DRIVERS_HOME_COUNT
    total += count_term

    return total, {
        "driver_specific": details,
        "drivers_home": len(home_ids),
        "drivers_away": away_ids,
        "count_term": round(count_term, 3),
        "weight_per_missing_driver": W_DRIVERS_HOME_COUNT,
        "note": "driver-specific signals attribute WHICH driver; the count "
                "term is a weak generic away-lean only.",
    }


def compute_hint(hass, vehicle: str, now: datetime | None = None) -> tuple[float, dict]:
    """Bayesian log-odds fusion of non-camera presence evidence.

    Returns (probability_0_1, audit_dict). Never raises on missing data:
    unavailable evidence contributes 0 and the time-of-day prior stands alone.
    """
    if now is None:
        now = dt_util.now() if dt_util is not None else datetime.now().astimezone()

    bucket, prior = _time_bucket(now)
    total = _logit(prior)
    evidence = []

    key_w, key_detail = _key_evidence(hass, vehicle)
    total += key_w
    evidence.append({"source": "keys", **key_detail})

    # Driver-aware evidence replaces the old generic family nudge: the
    # per-driver person hints already fuse each driver's person entity and
    # phone, so re-adding the raw family trackers here would double-count.
    drv_w, drv_detail = _driver_evidence(hass, vehicle, now)
    total += drv_w
    evidence.append({"source": "drivers", **drv_detail})

    probability = min(0.99, max(0.01, _sigmoid(total)))

    audit = {
        "vehicle": vehicle,
        "local_time": now.isoformat(timespec="minutes"),
        "time_bucket": bucket,
        "prior": round(prior, 3),
        "evidence": evidence,
        "total_log_odds": round(total, 3),
        "probability": round(probability, 4),
        "advisory": True,
        "note": "Hint only — not authoritative vehicle state. "
                "Camera-based vehicle sensors remain primary.",
    }
    return probability, audit
