# Poster Color

A small Home Assistant custom integration that extracts a usable colour from the
artwork (poster) a media player is currently showing, and exposes it as a sensor.
It is meant for ambient/cinema lighting: put the dominant colour of what you are
watching on a light ring, dimmed to a pleasant level.

Tested with an Apple TV 4K (tvOS) and Streamyfin/Plex, but it works with any
`media_player` entity that exposes `entity_picture`.

## How it works

- Watches one media player entity.
- When the title or artwork changes, downloads the artwork through Home
  Assistant's own media proxy (`127.0.0.1`) and extracts a palette with Pillow.
- Discards near-black, near-white and grey colours, caps saturation and lifts
  brightness so the result works as dim ambient light instead of a neon blob.
- Falls back to a warm amber when no artwork is available (common for Netflix
  on tvOS and some other streaming apps).

It updates once per title, not per frame. This is **not** an ambilight clone:
real-time colour requires HDMI capture hardware.

## Requirements

- Home Assistant 2026.x or newer (uses `SupportsResponse` for the service)
- `Pillow` — installed automatically from `manifest.json`

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add this repository's URL, category **Integration**
3. Install **Poster Color**, then restart Home Assistant

### Manual

Copy `custom_components/poster_color` into your `config/custom_components/`
folder and restart Home Assistant.

## Configuration

```yaml
sensor:
  - platform: poster_color
    media_player: media_player.living_room_apple_tv
    name: Living room
    # optional: add or override the app colours used when there is no artwork
    fallbacks:
      YouTube: [255, 40, 40]
      TiviMax: [0, 120, 200]
```

This creates `sensor.living_room_plakatfarge` (the configured `name` plus
` plakatfarge`; rename as you like).

Attributes on the sensor:

| Attribute | Meaning |
|---|---|
| `rgb_color` | The extracted colour as `[r, g, b]` |
| `media_title` | The title the colour came from |
| `app_name` | The app that was playing |
| `has_artwork` | `true` when a real poster was used |
| `fallback` | `true` when no artwork could be used |
| `color_source` | `artwork`, `app` or `amber` |

### Service

`poster_color.refresh` re-reads the current artwork and returns the result.
Useful for debugging without waiting for a new title:

```yaml
action: poster_color.refresh
target:
  entity_id: sensor.living_room_plakatfarge
```

## Example automation

`examples/kinomodus_stue.yaml` contains a complete cinema-mode automation:

- on `playing` → snapshot the lights, turn off the main lights, set the ring to
  the poster colour at ~8 % brightness
- on a new title → update the ring colour
- on `paused`/`off`/`standby` for 30 s → restore the snapshot
- treats `idle` as stopped after the delay, so closing an app restores the lights
- only runs when the sun is below the horizon

Replace the entity IDs in the example with your own.

If you use Blackshome's *Sensor Light* blueprint for presence lighting, add the
bypass shown at the bottom of the example so the presence automation does not
turn the lights back on (or off) during a movie.

## Limitations

- One colour per title, not per scene.
- Apps that expose no metadata/artwork use a per-app fallback colour: YouTube red,
  Netflix red, Viaplay purple, NRK blue, TV 2 blue, Disney+ blue, HBO Max purple,
  Plex orange, Streamyfin blue, Apple TV blue, Prime Video blue, Spotify green,
  VLC orange. Unknown apps use warm amber.
- The target light must support colour (`rgb_color`).
- Zigbee lights have noticeable latency and limited colour accuracy.
- The poster is analysed once per title change; there is no per-frame sync.

## Privacy and security

The integration only reads `entity_picture` from the configured media player and
fetches it through Home Assistant's media proxy on localhost. It stores nothing
and never logs artwork URLs or tokens.

Note that `entity_picture` URLs contain a signed media proxy token. Do not
publish debug logs or screenshots that show that URL.

## License

MIT — see [LICENSE](LICENSE).
