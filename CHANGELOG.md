# Changelog

## 0.2.1 – 2026-11-28

### Changed
- "When it is dark" now also starts cinema mode when the room is below the light-sensor level, if a light sensor is chosen (e.g. curtains closed in the daytime). Before, it only looked at sunset.

## 0.2.0 – 2026-11-27

### Added
- Set-up in the UI (config flow): one entry per room, with media player, area, colour lights, lights to turn off, brightness, transition, restore delay, when (dark/light sensor/always) and app colours. Everything can be changed later under Configure.
- Built-in cinema mode with a `switch` per room: snapshots the lights, follows the poster colour while playing and restores the lights after the delay. Lights can be picked by entity, device or area; unavailable lights are skipped.
- English and Norwegian (bokmål) translations.

### Changed
- **Breaking:** YAML configuration (`sensor: - platform: poster_color`) is removed. Add the room in the UI instead.

## 0.1.6 – 2026-11-27

### Added
- Automatic Jellyfin artwork: when the player gives no usable colour (no artwork, a black-and-white logo, a grey still) and Home Assistant's Jellyfin integration is playing the same title, the episode image, series poster and series backdrop are tried. No configuration or API key needed. Works for any Jellyfin client, also on Apple TV / Google TV.
- `artwork_source` attribute showing where the colour came from.

### Fixed
- Images fetched over HTTP were cut off after the first network chunk (since 0.1.4), so they could not be read. The whole body is read now, still capped at 5 MB.

## 0.1.5 – 2026-11-27

### Changed
- New colour picking. Every pixel votes for its hue, weighted by how colourful it is; the hue band with most votes wins. Greys, near-black and near-white do not vote.
- Skin tones get a quarter of a normal vote, so posters with large faces no longer come out peach/beige. A poster with a face and a red cape now gives red.
- Black-and-white or washed-out artwork falls back to the app colour instead of a generic peach.
- Higher saturation in the result (0.55–0.95), as LEDs wash out pale colours.

## 0.1.4 – 2026-11-23

### Fixed
- The image size check swallowed its own error, so oversized artwork was downloaded anyway.
- App fallback colours matched on substrings, giving false hits ("yle" in "style", "itv" in "activity", "plex" in "complex"). Matching is now on whole words / app-id segments.
- Sensors were never removed from the internal list on reload, so `poster_color.refresh` could call a removed entity.
- Example automation: a colour update could cancel the 30 s restore delay, leaving the lights in cinema mode. The wait is now `for: 30s` on the trigger, and the colour trigger only fires when `rgb_color` changes.

### Changed
- Artwork is fetched straight from the media player entity (`async_get_media_image`), falling back to the media proxy on `127.0.0.1`. Works with SSL-enabled Home Assistant.
- Uses `get_flattened_data()` when available, as `Image.getdata()` is removed in Pillow 14.
- Added `services.yaml`, `codeowners`, `issue_tracker`; `iot_class` is now `calculated`.
- README: requires Home Assistant 2023.7+ (not 2026.x).
