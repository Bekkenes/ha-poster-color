# Changelog

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
