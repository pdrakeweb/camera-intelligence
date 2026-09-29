"""Config flow for the Camera Intelligence integration.

Single-step, no user input required: the integration is fed by an external
agent over its local HTTP API, so setup is just a confirmation click.
"""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class CameraIntelligenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Camera Intelligence."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Confirm setup from the UI (no input needed)."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Camera Intelligence", data={})
        return self.async_show_form(step_id="user")

    async def async_step_import(self, import_config: dict[str, Any] | None):
        """Import a legacy YAML configuration."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(
            title="Camera Intelligence", data=dict(import_config or {})
        )
