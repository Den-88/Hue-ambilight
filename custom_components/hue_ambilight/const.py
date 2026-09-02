"""Constants for the Hue Ambilight integration."""

DOMAIN = "hue_ambilight"
CONF_TV_IP = "tv_ip"
CONF_TV_PORT = "tv_port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_LIGHTS = "lights"
CONF_LIGHTS_LEFT = "lights_left"
CONF_LIGHTS_RIGHT = "lights_right"
CONF_LIGHTS_TOP = "lights_top"
CONF_LIGHTS_BOTTOM = "lights_bottom"
CONF_LIGHTS_ALL = "lights_all"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SIDES = "sides"
CONF_TRANSITION = "transition"
CONF_BRIGHTNESS_FACTOR = "brightness_factor"

DEFAULT_PORT = 1926
DEFAULT_SCAN_INTERVAL = 500  # ms
DEFAULT_SIDES = ["left", "right", "top", "bottom"]
DEFAULT_TRANSITION = 0
DEFAULT_BRIGHTNESS_FACTOR = 1.0

API_VERSION = 6

# Sides of the screen used for color averaging
SIDES = ["left", "right", "top", "bottom"]

# Coordinator update interval in seconds (converted from ms)
MIN_SCAN_INTERVAL_MS = 200
MAX_SCAN_INTERVAL_MS = 5000

ATTR_COLOR_HEX = "color_hex"
ATTR_COLOR_R = "r"
ATTR_COLOR_G = "g"
ATTR_COLOR_B = "b"
ATTR_SIDES_COLORS = "sides_colors"
ATTR_TV_ONLINE = "tv_online"

PLATFORMS = ["switch", "sensor", "number"]
