"""Constants for the Camera Intelligence integration."""

DOMAIN = "camera_intelligence"

PLATFORMS = ["sensor"]

CONF_VEHICLES = "vehicles"
DEFAULT_VEHICLES = ["sportage", "sorento", "entourage", "sky", "qx80", "commander"]

API_UPDATE_PATH = "/api/camera_intelligence/update"
API_STATE_PATH = "/api/camera_intelligence/state"

SIGNAL_UPDATE = "camera_intelligence_update"

# Canonical states. The entity is named for the thing ("Sportage"); the state
# describes its status ("home"). Same pattern scales to animals, people, etc.
STATUS_HOME = "home"
STATUS_AWAY = "away"
STATUS_UNKNOWN = "unknown"
VALID_VEHICLE_STATUS = {STATUS_HOME, STATUS_AWAY, STATUS_UNKNOWN}

PRESENCE_PRESENT = "present"
PRESENCE_NONE = "none"

PACKAGE_DELIVERED = "delivered"
PACKAGE_NONE = "none"
