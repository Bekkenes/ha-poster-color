# Poster Color

A small Home Assistant custom integration that extracts a usable colour from the
artwork (poster) a media player is currently showing, and exposes it as a sensor.
It is meant for ambient/cinema lighting: put the dominant colour of what you are
watching on a light ring, dimmed to a pleasant level.

Tested with an Apple TV 4K (tvOS) and Streamyfin/Plex, but it works with any
`media_player` entity that exposes `entity_picture`.

## How it works

- Watches one media player entity.
- When the title or artwork changes, asks the media player entity for its
  artwork directly (falls back to Home Assistant's media proxy on `127.0.0.1`)
  and extracts a palette with Pillow.
- Picks the colour you would name for the image: every pixel votes for its hue,
  weighted by how colourful it is. Grey, near-black and near-white pixels do not
  vote, and skin tones only get a small vote, so big faces do not turn every
  poster peach.
- **Jellyfin (automatic):** if the player gives no usable colour (no artwork, a
  black-and-white logo, a grey still) and Home Assistant's
  [Jellyfin integration](https://www.home-assistant.io/integrations/jellyfin/)
  is playing the same title, the episode image, the series poster and the
  series backdrop are tried in that order. Nothing to configure and no API key:
  it reuses the Jellyfin connection Home Assistant already has. Works for any
  Jellyfin client (Moonfin, Streamyfin, Swiftfin, Infuse, the web client …),
  also when it plays on an Apple TV or Google TV.
- Falls back to a per-app colour, then warm amber, when there is still no
  colour (common for Netflix on tvOS and some other streaming apps).
- The sensor's `artwork_source` attribute tells where the colour came from:
  `media_player`, `jellyfin_episode`, `jellyfin_series` or `jellyfin_backdrop`.

It updates once per title, not per frame. This is **not** an ambilight clone:
real-time colour requires HDMI capture hardware.

## Requirements

- Home Assistant 2023.7 or newer (uses `SupportsResponse` for the service)
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
- on `paused`/`idle`/`off`/`standby` for 30 s → restore the snapshot (the
  30 s wait is in the trigger, so a colour update cannot cancel it)
- only reacts to colour changes when `rgb_color` actually changes
- only runs when the sun is below the horizon

Replace the entity IDs in the example with your own.

If you use Blackshome's *Sensor Light* blueprint for presence lighting, add the
bypass shown at the bottom of the example so the presence automation does not
turn the lights back on (or off) during a movie.

## Limitations

- One colour per title, not per scene.
- Apps that expose no metadata/artwork use a per-app fallback colour.

  **US:** YouTube, Netflix, Hulu, Peacock, Paramount+, Pluto TV, Tubi, Crunchyroll,
  Sling, Fubo, ESPN, Discovery+, AMC+, Starz, Prime Video, Disney+, HBO Max/Max,
  Plex, Streamyfin, Apple TV, Spotify, VLC.

  **Europe:** Viaplay, NRK, TV 2, TV 4, SVT, Yle, DR, BBC iPlayer, ITVX,
  Channel 4, NOW, Sky/SkyShowtime, RTÉ, RTL+, Joyn, ZDF, ARD Mediathek,
  France.tv, TF1, M6, RaiPlay, Movistar+, Rakuten TV, DAZN, Eurosport, MUBI,
  Twitch, Deezer, Tidal, SoundCloud, TiviMax.

  Unknown apps use warm amber. Add or override entries with the `fallbacks:`
  config key.
- The target light must support colour (`rgb_color`).
- Zigbee lights have noticeable latency and limited colour accuracy.
- The poster is analysed once per title change; there is no per-frame sync.

## Privacy and security

The integration asks the configured media player for its artwork directly, or
fetches `entity_picture` through Home Assistant's media proxy on localhost. With
Jellyfin it fetches images from your own Jellyfin server through Home
Assistant's existing connection. It stores nothing and never logs artwork URLs,
tokens or API keys.

Note that `entity_picture` URLs contain a signed media proxy token. Do not
publish debug logs or screenshots that show that URL.

## License

MIT — see [LICENSE](LICENSE).
