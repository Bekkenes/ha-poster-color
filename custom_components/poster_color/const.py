"""Constants for poster_color."""

DOMAIN = "poster_color"
DATA_ENTITIES = f"{DOMAIN}_entities"

CONF_MEDIA_PLAYER = "media_player"
CONF_NAME = "name"
CONF_FALLBACKS = "fallbacks"
CONF_AREA = "area"

# Light control (config entries only)
CONF_CONTROL_LIGHTS = "control_lights"
CONF_COLOR_LIGHTS = "color_lights"
CONF_OFF_LIGHTS = "off_lights"
CONF_BRIGHTNESS = "brightness"
CONF_TRANSITION = "transition"
CONF_RESTORE_DELAY = "restore_delay"
CONF_WHEN = "when"
CONF_LUX_SENSOR = "lux_sensor"
CONF_LUX_BELOW = "lux_below"

WHEN_ALWAYS = "always"
WHEN_DARK = "dark"
WHEN_LUX = "lux"

DEFAULT_BRIGHTNESS = 15
DEFAULT_TRANSITION = 2
DEFAULT_RESTORE_DELAY = 30
DEFAULT_LUX_BELOW = 20

COLOR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}
STOPPED_STATES = {"paused", "idle", "off", "standby", "unavailable", "unknown"}


def entry_config(entry) -> dict:
    """The room's settings: the options once saved from Configure, else the setup values."""
    return dict(entry.options) if entry.options else dict(entry.data)
