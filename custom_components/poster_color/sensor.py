"""Sensor med dominerende farge fra mediespillerens plakat/artwork."""

from __future__ import annotations

import asyncio
import colorsys
import logging
from io import BytesIO

import aiohttp
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.util import slugify

from . import CONF_MEDIA_PLAYER, CONF_NAME, DATA_ENTITIES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Varm amber når det ikke finnes artwork å hente farge fra.
FALLBACK_RGB = (255, 163, 72)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 15
ARTWORK_DELAY = 1.5

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(CONF_NAME, default="Plakatfarge"): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict | None = None,
) -> None:
    """Set up the poster color sensor."""
    if not hass.services.has_service(DOMAIN, "refresh"):

        async def _handle_refresh(call):
            wanted = call.data.get("entity_id")
            results: dict[str, dict] = {}
            for entity in hass.data.get(DATA_ENTITIES, []):
                if wanted and entity.entity_id not in wanted:
                    continue
                results[entity.entity_id] = await entity.async_refresh_now()
            return results

        hass.services.async_register(
            DOMAIN,
            "refresh",
            _handle_refresh,
            schema=vol.Schema({vol.Optional("entity_id"): cv.entity_ids}),
            supports_response=SupportsResponse.ONLY,
        )

    entity = PosterColorSensor(hass, config)
    hass.data.setdefault(DATA_ENTITIES, []).append(entity)
    async_add_entities([entity])


class PosterColorSensor(SensorEntity):
    """Dominant color of the artwork currently shown on a media player."""

    _attr_should_poll = False
    _attr_icon = "mdi:palette"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._media_player: str = config[CONF_MEDIA_PLAYER]
        self._attr_name = f"{config[CONF_NAME]} plakatfarge"
        self._attr_unique_id = f"poster_color_{slugify(self._media_player)}"
        self._attr_native_value = None

        self._rgb: list[int] | None = None
        self._title: str | None = None
        self._app: str | None = None
        self._has_artwork = False
        self._fallback = True

        self._last_key: tuple[str | None, str | None] = (None, None)
        self._cancel_delay = None
        self._lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        self._last_key = self._current_key()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._media_player], self._handle_state_change
            )
        )
        if self._last_key != (None, None):
            self._schedule_refresh()

    @callback
    def _handle_state_change(self, event) -> None:
        key = self._current_key()
        if key == self._last_key:
            return
        self._last_key = key
        self._schedule_refresh()

    def _current_key(self) -> tuple[str | None, str | None]:
        state = self.hass.states.get(self._media_player)
        if state is None:
            return (None, None)
        return (
            state.attributes.get("media_title"),
            state.attributes.get("entity_picture"),
        )

    @callback
    def _schedule_refresh(self) -> None:
        if self._cancel_delay is not None:
            self._cancel_delay()
        self._cancel_delay = async_call_later(
            self.hass, ARTWORK_DELAY, self._delayed_refresh
        )

    async def _delayed_refresh(self, _now) -> None:
        self._cancel_delay = None
        await self.async_refresh_now()

    async def async_refresh_now(self) -> dict:
        """Fetch the artwork and work out a color. Safe to call from a service."""
        async with self._lock:
            state = self.hass.states.get(self._media_player)
            if state is None:
                return {
                    "entity_id": self.entity_id,
                    "error": "media_player finnes ikke",
                }

            title = state.attributes.get("media_title")
            app = state.attributes.get("app_name")
            picture = state.attributes.get("entity_picture")

            rgb: tuple[int, int, int] | None = None
            palette_size = 0
            has_artwork = False

            if picture:
                try:
                    raw = await self._fetch_image(picture)
                    rgb, palette_size = await self.hass.async_add_executor_job(
                        _extract_color, raw
                    )
                    has_artwork = True
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Kunne ikke hente plakatfarge for %s: %s",
                        self._media_player,
                        err,
                    )

            if rgb is None:
                rgb = FALLBACK_RGB

            self._rgb = [int(channel) for channel in rgb]
            self._title = title
            self._app = app
            self._has_artwork = has_artwork
            self._fallback = not has_artwork
            self._attr_native_value = "#{:02x}{:02x}{:02x}".format(*rgb)
            self.async_write_ha_state()

            return {
                "entity_id": self.entity_id,
                "title": title,
                "app": app,
                "rgb_color": self._rgb,
                "hex": self._attr_native_value,
                "has_artwork": has_artwork,
                "fallback": self._fallback,
                "palette_size": palette_size,
            }

    async def _fetch_image(self, picture: str) -> bytes:
        url = picture
        if url.startswith("/"):
            port = getattr(self.hass.http, "server_port", 8123)
            url = f"http://127.0.0.1:{port}{url}"
        elif not url.startswith(("http://", "https://")):
            raise ValueError("ukjent format på entity_picture")

        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with session.get(url, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > MAX_IMAGE_BYTES:
                        raise ValueError("bildet er for stort")
                except ValueError:
                    pass
            raw = await response.read()

        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("bildet er for stort")
        return raw

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "media_player": self._media_player,
            "media_title": self._title,
            "app_name": self._app,
            "rgb_color": self._rgb,
            "has_artwork": self._has_artwork,
            "fallback": self._fallback,
        }


def _extract_color(raw: bytes) -> tuple[tuple[int, int, int], int]:
    """Pick a usable color from an image. Runs in the executor."""
    from PIL import Image  # importeres her så manglende Pillow ikke velter oppstarten

    with Image.open(BytesIO(raw)) as source:
        image = source.convert("RGB")
        image.thumbnail((128, 128))
        quantized = image.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        colors = quantized.getcolors() or []

        best: tuple[int, int, int] | None = None
        best_score = -1.0

        for count, index in colors:
            offset = index * 3
            if offset + 2 >= len(palette):
                continue
            red, green, blue = palette[offset : offset + 3]
            _, saturation, value = colorsys.rgb_to_hsv(
                red / 255, green / 255, blue / 255
            )

            # Hopp over nesten-sort, nesten-hvitt og gråtoner.
            if value < 0.10:
                continue
            if saturation < 0.10 and value > 0.82:
                continue

            score = (count**0.40) * (0.20 + saturation) * (1.0 - abs(value - 0.55))
            if score > best_score:
                best_score = score
                best = (red, green, blue)

        if best is None:
            pixels = [
                pixel
                for pixel in image.getdata()
                if max(pixel) > 24 and min(pixel) < 235
            ]
            if not pixels:
                raise ValueError("fant ingen brukbare farger")
            best = tuple(
                sum(channel) // len(pixels) for channel in zip(*pixels)
            )  # type: ignore[assignment]

    hue, saturation, _ = colorsys.rgb_to_hsv(*(channel / 255 for channel in best))
    if saturation < 0.12:
        hue = 0.085  # varm amber
        saturation = 0.55
    else:
        saturation = min(max(saturation * 1.1, 0.45), 0.78)

    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 0.92)
    return (
        (round(red * 255), round(green * 255), round(blue * 255)),
        len(colors),
    )
