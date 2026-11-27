"""Set up Poster Color from the UI: one entry per room / media player."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AREA,
    CONF_BRIGHTNESS,
    CONF_COLOR_LIGHTS,
    CONF_CONTROL_LIGHTS,
    CONF_FALLBACKS,
    CONF_LUX_BELOW,
    CONF_LUX_SENSOR,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    CONF_OFF_LIGHTS,
    CONF_RESTORE_DELAY,
    CONF_TRANSITION,
    CONF_WHEN,
    DEFAULT_BRIGHTNESS,
    DEFAULT_LUX_BELOW,
    DEFAULT_RESTORE_DELAY,
    DEFAULT_TRANSITION,
    DOMAIN,
    WHEN_ALWAYS,
    WHEN_DARK,
    WHEN_LUX,
    entry_config,
)


def _number(minimum: float, maximum: float, step: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=step, unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.SLIDER,
        )
    )


def _optional(key: str, values: dict[str, Any]) -> vol.Optional:
    """An optional field that shows the saved value, and can be cleared."""
    if values.get(key) not in (None, "", {}):
        return vol.Optional(key, description={"suggested_value": values[key]})
    return vol.Optional(key)


def _settings_schema(values: dict[str, Any]) -> dict:
    lights = selector.TargetSelector(
        selector.TargetSelectorConfig(entity=selector.EntityFilterSelectorConfig(domain="light"))
    )
    return {
        _optional(CONF_AREA, values): selector.AreaSelector(),
        vol.Required(CONF_CONTROL_LIGHTS, default=values.get(CONF_CONTROL_LIGHTS, True)): selector.BooleanSelector(),
        _optional(CONF_COLOR_LIGHTS, values): lights,
        _optional(CONF_OFF_LIGHTS, values): lights,
        vol.Required(CONF_BRIGHTNESS, default=values.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)): _number(1, 100, 1, "%"),
        vol.Required(CONF_TRANSITION, default=values.get(CONF_TRANSITION, DEFAULT_TRANSITION)): _number(0, 10, 0.5, "s"),
        vol.Required(CONF_RESTORE_DELAY, default=values.get(CONF_RESTORE_DELAY, DEFAULT_RESTORE_DELAY)): _number(0, 300, 5, "s"),
        vol.Required(CONF_WHEN, default=values.get(CONF_WHEN, WHEN_DARK)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[WHEN_DARK, WHEN_LUX, WHEN_ALWAYS],
                translation_key=CONF_WHEN,
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        _optional(CONF_LUX_SENSOR, values): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
        ),
        vol.Required(CONF_LUX_BELOW, default=values.get(CONF_LUX_BELOW, DEFAULT_LUX_BELOW)): _number(0, 500, 1, "lx"),
        _optional(CONF_FALLBACKS, values): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
    }


class PosterColorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a room."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_MEDIA_PLAYER])
            self._abort_if_unique_id_configured()
            name = user_input.pop(CONF_NAME)
            return self.async_create_entry(title=name, data=user_input)

        schema = {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            **_settings_schema({}),
        }
        return self.async_show_form(step_id="user", data_schema=vol.Schema(schema))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PosterColorOptionsFlow()


class PosterColorOptionsFlow(OptionsFlow):
    """Change a room's settings (Configure)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        values = entry_config(self.config_entry)
        schema = {
            vol.Required(CONF_MEDIA_PLAYER, default=values[CONF_MEDIA_PLAYER]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            **_settings_schema(values),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
