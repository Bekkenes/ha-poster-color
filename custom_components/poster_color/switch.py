"""Cinema mode: lights follow the poster while something plays."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    entry_config,
    COLOR_MODES,
    CONF_BRIGHTNESS,
    CONF_COLOR_LIGHTS,
    CONF_CONTROL_LIGHTS,
    CONF_LUX_BELOW,
    CONF_LUX_SENSOR,
    CONF_MEDIA_PLAYER,
    CONF_OFF_LIGHTS,
    CONF_RESTORE_DELAY,
    CONF_TRANSITION,
    CONF_WHEN,
    DEFAULT_BRIGHTNESS,
    DEFAULT_LUX_BELOW,
    DEFAULT_RESTORE_DELAY,
    DEFAULT_TRANSITION,
    DOMAIN,
    STOPPED_STATES,
    WHEN_ALWAYS,
    WHEN_DARK,
    WHEN_LUX,
)
from .sensor import device_info

_LOGGER = logging.getLogger(__name__)
FALLBACK_RGB = [255, 163, 72]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    config = entry_config(entry)
    if config.get(CONF_CONTROL_LIGHTS, True):
        async_add_entities([CinemaModeSwitch(hass, entry, config)])


def resolve_lights(hass: HomeAssistant, target: dict | None, color_only: bool) -> list[str]:
    """Light entity IDs from a target selector (entities, devices and areas).

    Resolved every time, so lights added to a chosen area later are included.
    """
    if not target:
        return []
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    def as_list(value) -> list[str]:
        if not value:
            return []
        return [value] if isinstance(value, str) else list(value)

    ids: set[str] = set(as_list(target.get("entity_id")))
    device_ids = set(as_list(target.get("device_id")))
    for area_id in as_list(target.get("area_id")):
        ids.update(e.entity_id for e in er.async_entries_for_area(ent_reg, area_id))
        for device in dr.async_entries_for_area(dev_reg, area_id):
            device_ids.add(device.id)
            ids.update(
                e.entity_id
                for e in er.async_entries_for_device(ent_reg, device.id)
                if e.area_id in (None, area_id)
            )
    for device_id in device_ids:
        ids.update(e.entity_id for e in er.async_entries_for_device(ent_reg, device_id))

    result = []
    for entity_id in sorted(ids):
        if not entity_id.startswith("light."):
            continue
        entry = ent_reg.async_get(entity_id)
        if entry is not None and (entry.disabled_by or entry.hidden_by):
            continue
        state = hass.states.get(entity_id)
        if state is None or state.state == "unavailable":
            # Lights switched off at the wall are left alone, never an error.
            continue
        if color_only:
            modes = set(state.attributes.get("supported_color_modes") or [])
            if not modes & COLOR_MODES:
                continue
        result.append(entity_id)
    return result


class CinemaModeSwitch(SwitchEntity, RestoreEntity):
    """On = lights follow the poster colour while something is playing."""

    _attr_has_entity_name = True
    _attr_translation_key = "cinema_mode"
    _attr_icon = "mdi:movie-open-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, config: dict) -> None:
        self.hass = hass
        self._entry = entry
        self._config = config
        self._media_player: str = config[CONF_MEDIA_PLAYER]
        self._attr_unique_id = f"{entry.entry_id}_cinema_mode"
        self._attr_device_info = device_info(entry)
        self._attr_is_on = True
        self._active = False  # lights are currently in cinema mode
        self._scene_id = f"poster_color_{entry.entry_id.lower()}"
        self._sensor_id: str | None = None
        self._cancel_restore = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"active": self._active}

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state != "off"
        ent_reg = er.async_get(self.hass)
        self._sensor_id = ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{self._entry.entry_id}_poster_color"
        )
        watched = [self._media_player] + ([self._sensor_id] if self._sensor_id else [])
        self.async_on_remove(
            async_track_state_change_event(self.hass, watched, self._handle_change)
        )

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_restore_timer()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        player = self.hass.states.get(self._media_player)
        if player is not None and player.state == "playing":
            await self._start()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        await self._restore()
        self.async_write_ha_state()

    @callback
    def _handle_change(self, event: Event) -> None:
        if not self._attr_is_on:
            return
        entity_id = event.data["entity_id"]
        new = event.data.get("new_state")
        if new is None:
            return
        if entity_id == self._media_player:
            if new.state == "playing":
                self._cancel_restore_timer()
                self.hass.async_create_task(self._start())
            elif new.state in STOPPED_STATES and self._active and self._cancel_restore is None:
                delay = self._config.get(CONF_RESTORE_DELAY, DEFAULT_RESTORE_DELAY)
                self._cancel_restore = async_call_later(self.hass, delay, self._restore_later)
        elif entity_id == self._sensor_id and self._active:
            old = event.data.get("old_state")
            old_rgb = old.attributes.get("rgb_color") if old else None
            if new.attributes.get("rgb_color") != old_rgb:
                self.hass.async_create_task(self._set_color())

    @callback
    def _cancel_restore_timer(self) -> None:
        if self._cancel_restore is not None:
            self._cancel_restore()
            self._cancel_restore = None

    async def _restore_later(self, _now) -> None:
        self._cancel_restore = None
        player = self.hass.states.get(self._media_player)
        if player is None or player.state != "playing":
            await self._restore()

    def _dark_enough(self) -> bool:
        when = self._config.get(CONF_WHEN, WHEN_DARK)
        if when == WHEN_ALWAYS:
            return True
        if when == WHEN_LUX and self._config.get(CONF_LUX_SENSOR):
            state = self.hass.states.get(self._config[CONF_LUX_SENSOR])
            try:
                return float(state.state) < float(self._config.get(CONF_LUX_BELOW, DEFAULT_LUX_BELOW))
            except (AttributeError, TypeError, ValueError):
                pass  # sensor unavailable: fall back to the sun
        sun = self.hass.states.get("sun.sun")
        return sun is None or sun.state == "below_horizon"

    def _color_lights(self) -> list[str]:
        return resolve_lights(self.hass, self._config.get(CONF_COLOR_LIGHTS), True)

    def _off_lights(self) -> list[str]:
        color = set(self._color_lights())
        return [
            light
            for light in resolve_lights(self.hass, self._config.get(CONF_OFF_LIGHTS), False)
            if light not in color
        ]

    async def _start(self) -> None:
        if self._active:
            await self._set_color()
            return
        if not self._dark_enough():
            return
        color, off = self._color_lights(), self._off_lights()
        if not color and not off:
            return
        await self.hass.services.async_call(
            "scene",
            "create",
            {"scene_id": self._scene_id, "snapshot_entities": color + off},
            blocking=True,
        )
        self._active = True
        self.async_write_ha_state()
        transition = self._config.get(CONF_TRANSITION, DEFAULT_TRANSITION)
        if off:
            await self.hass.services.async_call(
                "light", "turn_off", {"entity_id": off, "transition": transition}, blocking=True
            )
        await self._set_color()

    async def _set_color(self) -> None:
        lights = self._color_lights()
        if not lights:
            return
        sensor = self.hass.states.get(self._sensor_id) if self._sensor_id else None
        rgb = (sensor.attributes.get("rgb_color") if sensor else None) or FALLBACK_RGB
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {
                "entity_id": lights,
                "rgb_color": rgb,
                "brightness_pct": self._config.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS),
                "transition": self._config.get(CONF_TRANSITION, DEFAULT_TRANSITION),
            },
            blocking=True,
        )

    async def _restore(self) -> None:
        self._cancel_restore_timer()
        if not self._active:
            return
        self._active = False
        self.async_write_ha_state()
        try:
            await self.hass.services.async_call(
                "scene",
                "turn_on",
                {
                    "entity_id": f"scene.{self._scene_id}",
                    "transition": self._config.get(CONF_TRANSITION, DEFAULT_TRANSITION),
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunne ikke gjenopprette lyset: %s", err)
