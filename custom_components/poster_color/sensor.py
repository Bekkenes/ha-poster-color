"""Sensor med dominerende farge fra mediespillerens plakat/artwork."""

from __future__ import annotations

import asyncio
import colorsys
import math
import logging
import re
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

from . import (
    CONF_FALLBACKS,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DATA_ENTITIES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Varm amber når det ikke finnes artwork å hente farge fra.
FALLBACK_RGB = (255, 163, 72)

# Farge per app når plakat mangler. Matches mot app_name og app_id.
APP_FALLBACKS = (
    (("youtube",), (255, 40, 40)),
    (("netflix",), (229, 9, 20)),
    (("viaplay",), (150, 90, 255)),
    (("nrk",), (0, 120, 200)),
    (("tv2",), (0, 90, 210)),
    (("tv4",), (230, 0, 40)),
    (("disney",), (60, 80, 220)),
    (("tivimax",), (0, 120, 200)),
    (("hbomax", "hbo", "max"), (120, 40, 220)),
    (("plex",), (229, 160, 13)),
    (("streamyfin",), (70, 150, 255)),
    (("appletv", "tvwatchlist"), (120, 140, 255)),
    (("primevideo", "aiv"), (0, 150, 220)),
    (("spotify",), (30, 200, 90)),
    (("vlc",), (255, 130, 0)),
    # USA
    (("hulu",), (30, 215, 130)),
    (("peacock",), (250, 200, 40)),
    (("paramount",), (0, 100, 255)),
    (("pluto",), (255, 210, 0)),
    (("tubi",), (250, 80, 250)),
    (("crunchyroll",), (244, 117, 33)),
    (("sling",), (0, 160, 220)),
    (("fubo",), (255, 100, 0)),
    (("espn",), (200, 0, 0)),
    (("discovery",), (0, 160, 220)),
    (("amc",), (240, 190, 20)),
    (("starz",), (220, 190, 80)),
    # Europa
    (("britbox",), (60, 120, 220)),
    (("bbc",), (255, 60, 140)),
    (("itv",), (0, 180, 180)),
    (("channel4",), (140, 60, 220)),
    (("now",), (0, 180, 90)),
    (("sky",), (0, 110, 200)),
    (("rte",), (0, 120, 200)),
    (("svt",), (0, 90, 170)),
    (("yle",), (0, 180, 220)),
    (("drtv",), (200, 0, 40)),
    (("rtl",), (230, 0, 80)),
    (("joyn",), (255, 100, 0)),
    (("zdf",), (250, 130, 0)),
    (("ardmediathek",), (0, 60, 130)),
    (("francetv",), (0, 85, 165)),
    (("tf1",), (0, 50, 160)),
    (("m6",), (230, 0, 40)),
    (("raiplay",), (0, 100, 200)),
    (("movistar",), (0, 150, 240)),
    (("rakuten",), (200, 0, 60)),
    (("dazn",), (200, 255, 0)),
    (("eurosport",), (0, 80, 200)),
    (("mubi",), (240, 200, 0)),
    (("twitch",), (145, 70, 255)),
    (("deezer",), (160, 60, 255)),
    (("tidal",), (0, 220, 255)),
    (("soundcloud",), (255, 85, 0)),
)

MEDIA_PLAYER_DOMAIN = "media_player"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 15
ARTWORK_DELAY = 1.5
JELLYFIN_RETRY = 8

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(CONF_NAME, default="Plakatfarge"): cv.string,
        vol.Optional(CONF_FALLBACKS, default={}): vol.Schema(
            {
                cv.string: vol.All(
                    [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))],
                    vol.Length(min=3, max=3),
                )
            }
        ),
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
        self._fallbacks: dict = config.get(CONF_FALLBACKS) or {}
        self._attr_name = f"{config[CONF_NAME]} plakatfarge"
        self._attr_unique_id = f"poster_color_{slugify(self._media_player)}"
        self._attr_native_value = None

        self._rgb: list[int] | None = None
        self._title: str | None = None
        self._app: str | None = None
        self._has_artwork = False
        self._fallback = True
        self._color_source = "amber"
        self._artwork_source: str | None = None
        self._jellyfin_retry = None
        self._jellyfin_retried: tuple[str | None, str | None] | None = None

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

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_delay is not None:
            self._cancel_delay()
            self._cancel_delay = None
        if self._jellyfin_retry is not None:
            self._jellyfin_retry()
            self._jellyfin_retry = None
        entities = self.hass.data.get(DATA_ENTITIES, [])
        if self in entities:
            entities.remove(self)

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
            app_id = state.attributes.get("app_id")
            picture = state.attributes.get("entity_picture")

            rgb: tuple[int, int, int] | None = None
            palette_size = 0
            has_artwork = False
            source = "artwork"

            artwork_source = None
            if picture:
                try:
                    raw = await self._fetch_image(picture)
                    rgb, palette_size = await self.hass.async_add_executor_job(
                        _extract_color, raw
                    )
                    has_artwork = True
                    artwork_source = "media_player"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Kunne ikke hente plakatfarge for %s: %s",
                        self._media_player,
                        err,
                    )

            if rgb is None and title:
                # The player gave no usable colour (no artwork, a black-and-white
                # logo, a grey still). If Jellyfin is playing the same thing, try
                # the episode image and the series poster from there.
                found, images = self._jellyfin_images(
                    title, state.attributes.get("media_series_title")
                )
                for label, url in images:
                    try:
                        raw = await self._fetch_from_url(url)
                        rgb, palette_size = await self.hass.async_add_executor_job(
                            _extract_color, raw
                        )
                        has_artwork = True
                        artwork_source = label
                        break
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.debug("Jellyfin %s ga ingen farge: %s", label, type(err).__name__)
                if not found and self._jellyfin_available():
                    # Jellyfin often reports the session a few seconds after the
                    # player does; look once more shortly.
                    self._schedule_jellyfin_retry()

            if rgb is None:
                rgb, source = _fallback_color(app, app_id, self._fallbacks)

            self._rgb = [int(channel) for channel in rgb]
            self._title = title
            self._app = app
            self._has_artwork = has_artwork
            self._fallback = source != "artwork"
            self._color_source = source
            self._artwork_source = artwork_source
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
                "color_source": source,
                "artwork_source": artwork_source,
                "palette_size": palette_size,
            }

    def _jellyfin_available(self) -> bool:
        entries = self.hass.config_entries
        if hasattr(entries, "async_loaded_entries"):
            return bool(entries.async_loaded_entries("jellyfin"))
        return bool(entries.async_entries("jellyfin"))

    @callback
    def _schedule_jellyfin_retry(self) -> None:
        if self._jellyfin_retry is not None or self._jellyfin_retried == self._last_key:
            return
        self._jellyfin_retried = self._last_key

        async def _retry(_now) -> None:
            self._jellyfin_retry = None
            if self._color_source != "artwork":
                await self.async_refresh_now()

        self._jellyfin_retry = async_call_later(self.hass, JELLYFIN_RETRY, _retry)

    def _jellyfin_images(
        self, title: str, series_title: str | None
    ) -> tuple[bool, list[tuple[str, str]]]:
        """Image URLs for what Jellyfin is playing, if it matches this player.

        Uses Home Assistant's own Jellyfin integration, so no extra setup or API
        key is needed. Returns (session found, [(label, url), ...]).
        """
        component = self.hass.data.get(MEDIA_PLAYER_DOMAIN)
        wanted = {_normalise(value) for value in (title, series_title) if value}
        match = None
        for entity in list(getattr(component, "entities", None) or []):
            platform = getattr(entity, "platform", None)
            if getattr(platform, "platform_name", None) != "jellyfin":
                continue
            item = getattr(entity, "now_playing", None)
            if not item:
                continue
            if entity.entity_id == self._media_player:
                match = entity
                break
            names = {
                _normalise(item.get(key))
                for key in ("SeriesName", "Name", "Album")
                if item.get(key)
            }
            if wanted & names:
                match = entity
        if match is None:
            return False, []

        item = match.now_playing
        client = getattr(getattr(match, "coordinator", None), "api_client", None)
        api = getattr(client, "jellyfin", None)
        if api is None:
            return True, []

        candidates: list[tuple[str, str, str]] = []
        tags = item.get("ImageTags") or {}
        if "Primary" in tags:
            candidates.append(("jellyfin_episode", item["Id"], "Primary"))
        if item.get("SeriesId"):
            candidates.append(("jellyfin_series", item["SeriesId"], "Primary"))
        backdrop = item.get("ParentBackdropItemId") or (
            item["Id"] if item.get("BackdropImageTags") else None
        )
        if backdrop:
            candidates.append(("jellyfin_backdrop", backdrop, "Backdrop"))

        images: list[tuple[str, str]] = []
        for label, item_id, art in candidates:
            try:
                images.append((label, api.artwork(item_id, art, 500)))
            except Exception:  # noqa: BLE001
                continue
        return True, images

    async def _fetch_image(self, picture: str) -> bytes:
        raw = await self._fetch_from_entity()
        if raw is None:
            raw = await self._fetch_from_url(picture)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("bildet er for stort")
        return raw

    async def _fetch_from_entity(self) -> bytes | None:
        """Ask the media player entity for its image directly (no HTTP, no token).

        Works regardless of SSL/port setup. Returns None if not possible.
        """
        component = self.hass.data.get(MEDIA_PLAYER_DOMAIN)
        get_entity = getattr(component, "get_entity", None)
        if get_entity is None:
            return None
        entity = get_entity(self._media_player)
        if entity is None:
            return None
        try:
            async with asyncio.timeout(FETCH_TIMEOUT):
                raw, _content_type = await entity.async_get_media_image()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Direkte bildehenting feilet for %s: %s", self._media_player, err)
            return None
        return raw or None

    async def _fetch_from_url(self, picture: str) -> bytes:
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
            length = response.content_length
            if length is not None and length > MAX_IMAGE_BYTES:
                raise ValueError("bildet er for stort")
            raw = await response.content.read(MAX_IMAGE_BYTES + 1)
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
            "color_source": self._color_source,
            "artwork_source": self._artwork_source,
        }


# Hue band for skin tones (roughly 5–42 degrees). Faces often fill a large part
# of a poster but are rarely the colour you remember the poster by.
SKIN_HUE = (0.015, 0.115)
HUE_BINS = 24
MIN_COLOURFUL_SHARE = 0.03


def _extract_color(raw: bytes) -> tuple[tuple[int, int, int], int]:
    """Pick the colour a person would name for an image. Runs in the executor.

    Every pixel votes for its hue, weighted by how colourful it is. Greys,
    near-black and near-white pixels do not vote, and skin tones get a much
    smaller vote. The hue band with the most votes wins, so a poster with a
    big face and a red cape comes out red, not peach.
    """
    from PIL import Image  # importeres her så manglende Pillow ikke velter oppstarten

    with Image.open(BytesIO(raw)) as source:
        image = source.convert("RGB")
        image.thumbnail((96, 96))
        pixels = list(_pixels(image))

    if not pixels:
        raise ValueError("tomt bilde")

    bins = [0.0] * HUE_BINS
    samples: list[tuple[float, float, float]] = []  # (hue, saturation, weight)
    for red, green, blue in pixels:
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if value < 0.15 or saturation < 0.18:
            continue
        weight = (saturation**1.5) * max(0.2, 1.0 - abs(value - 0.6) * 1.4)
        if SKIN_HUE[0] <= hue <= SKIN_HUE[1] and saturation < 0.62 and value > 0.35:
            weight *= 0.25
        bins[int(hue * HUE_BINS) % HUE_BINS] += weight
        samples.append((hue, saturation, weight))

    total = sum(bins)
    if total / len(pixels) < MIN_COLOURFUL_SHARE:
        # Black-and-white or washed-out artwork: let the app colour decide.
        raise ValueError("bildet har for lite farge")

    # Smooth over neighbouring bins so a hue split across a bin edge still wins.
    smoothed = [
        bins[(i - 1) % HUE_BINS] * 0.5 + bins[i] + bins[(i + 1) % HUE_BINS] * 0.5
        for i in range(HUE_BINS)
    ]
    winner = max(range(HUE_BINS), key=smoothed.__getitem__)
    width = 1.5 / HUE_BINS  # winning bin plus half a bin on each side

    # Weighted circular mean of the hues inside the winning band.
    sin_sum = cos_sum = sat_sum = weight_sum = 0.0
    centre = (winner + 0.5) / HUE_BINS
    for hue, saturation, weight in samples:
        distance = abs((hue - centre + 0.5) % 1.0 - 0.5)
        if distance > width:
            continue
        angle = hue * 2 * math.pi
        sin_sum += math.sin(angle) * weight
        cos_sum += math.cos(angle) * weight
        sat_sum += saturation * weight
        weight_sum += weight

    hue = (math.atan2(sin_sum, cos_sum) / (2 * math.pi)) % 1.0
    saturation = sat_sum / weight_sum
    # LEDs wash out pale colours, so push saturation up for the light.
    saturation = min(max(saturation * 1.15, 0.55), 0.95)

    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 0.92)
    used_bins = sum(1 for value in bins if value > total * 0.05)
    return (
        (round(red * 255), round(green * 255), round(blue * 255)),
        used_bins,
    )


def _pixels(image):
    """Pixel iterator that works on both old and new Pillow (getdata goes away in 14)."""
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened is not None else image.getdata()


def _normalise(value: str | None) -> str:
    """Lowercase and strip everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _candidates(app_name: str | None, app_id: str | None) -> set[str]:
    """Words to match app fallbacks against.

    "TV 2 Play" -> {"tv", "2", "play", "tv2play"}; "com.netflix.Netflix" ->
    {"com", "netflix"}. Matching is done on the start of each word, so "itv"
    matches "itvx" but no longer "activity", and "yle" no longer matches "style".
    """
    words: set[str] = set()
    for value in (app_name, app_id):
        if not value:
            continue
        parts = [_normalise(part) for part in re.split(r"[^A-Za-z0-9]+", value)]
        words.update(part for part in parts if part)
        whole = _normalise(value)
        if whole:
            words.add(whole)
    return words


def _matches(token: str, words: set[str]) -> bool:
    return bool(token) and any(word.startswith(token) for word in words)


def _fallback_color(
    app_name: str | None,
    app_id: str | None,
    overrides: dict,
) -> tuple[tuple[int, int, int], str]:
    """Pick a colour for the app when there is no artwork to analyse."""
    words = _candidates(app_name, app_id)

    for key, rgb in (overrides or {}).items():
        if _matches(_normalise(key), words):
            return tuple(int(channel) for channel in rgb), "app"

    for tokens, rgb in APP_FALLBACKS:
        if any(_matches(token, words) for token in tokens):
            return rgb, "app"

    return FALLBACK_RGB, "amber"
