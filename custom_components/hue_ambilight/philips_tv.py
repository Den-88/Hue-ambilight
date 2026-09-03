import base64
import hashlib
import hmac
import logging
import time
from typing import Any

import requests
from requests.auth import HTTPDigestAuth
import urllib3

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://{host}:{port}/{version}"
PAIR_DEVICE_NAME = "HomeAssistant"
PAIR_DEVICE_ID = "homeassistant_hue_ambilight"

# Master shared key for Philips JointSpace HMAC signatures
AUTH_SHARED_KEY = base64.b64decode(
    "ZmVay1EQVFOaZhwQ4Kv81ypLAZNczV9sG4KkseXWn1NEk6cXmPKO/MCa9sryslvLCFMnNe4Z4CPXzToowvhHvA=="
)


class PhilipsTVError(Exception):
    """Base exception for Philips TV API errors."""


class PhilipsTVAuthError(PhilipsTVError):
    """Authentication failed."""


class PhilipsTVOfflineError(PhilipsTVError):
    """TV is offline or unreachable."""


class PhilipsTVClient:
    """Client for the Philips TV JointSpace API (v6, HTTPS, Digest Auth)."""

    def __init__(
        self,
        host: str,
        port: int = 1926,
        api_version: int = 6,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        self.host = host
        self.port = port
        self.api_version = api_version
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session = requests.Session()
        self._session.verify = False  # Philips TV uses self-signed certs

        # Suppress InsecureRequestWarning
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _url(self, path: str) -> str:
        return f"https://{self.host}:{self.port}/{self.api_version}/{path.lstrip('/')}"

    def _auth(self) -> HTTPDigestAuth | None:
        if self.username and self.password:
            return HTTPDigestAuth(self.username, self.password)
        return None

    def _get(self, path: str) -> dict[str, Any]:
        url = self._url(path)
        try:
            resp = self._session.get(url, auth=self._auth(), timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError as err:
            raise PhilipsTVOfflineError(f"Cannot connect to TV at {self.host}: {err}") from err
        except requests.exceptions.Timeout as err:
            raise PhilipsTVOfflineError(f"Timeout connecting to TV at {self.host}") from err
        except requests.exceptions.HTTPError as err:
            if resp.status_code == 401:
                raise PhilipsTVAuthError("Authentication failed. Re-pair the TV.") from err
            raise PhilipsTVError(f"HTTP error {resp.status_code}: {err}") from err
        except Exception as err:
            raise PhilipsTVError(f"Unexpected error: {err}") from err

    def _post(
        self,
        path: str,
        data: dict[str, Any],
        auth: HTTPDigestAuth | None = None,
    ) -> dict[str, Any] | None:
        """POST request. Uses instance credentials by default; pass auth= to override."""
        url = self._url(path)
        auth_to_use = auth if auth is not None else self._auth()
        try:
            resp = self._session.post(url, json=data, auth=auth_to_use, timeout=self.timeout)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return None
        except requests.exceptions.ConnectionError as err:
            raise PhilipsTVOfflineError(f"Cannot connect to TV at {self.host}: {err}") from err
        except requests.exceptions.Timeout:
            raise PhilipsTVOfflineError("Timeout connecting to TV")
        except requests.exceptions.HTTPError as err:
            # Log the actual response body AND headers to diagnose auth requirements
            try:
                body = resp.text[:500]
            except Exception:  # noqa: BLE001
                body = "<unreadable>"
            _LOGGER.debug(
                "HTTP %d from %s\n  Headers: %s\n  Body: %s",
                resp.status_code, url, dict(resp.headers), body,
            )
            if resp.status_code == 401:
                raise PhilipsTVAuthError("Authentication failed.") from err
            raise PhilipsTVError(f"HTTP error {resp.status_code}: {err}") from err

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    def pair_request(self) -> tuple[str, Any]:
        """Step 1: request a PIN to be shown on the TV screen."""
        payload = {
            "scope": ["read", "write", "control"],
            "device": {
                "app_id": PAIR_DEVICE_ID,
                "id": PAIR_DEVICE_ID,
                "device_name": PAIR_DEVICE_NAME,
                "type": "native",
                "app_name": PAIR_DEVICE_NAME,
            },
        }
        result = self._post("pair/request", payload)
        if not result:
            raise PhilipsTVError("Empty response from pair/request")
        _LOGGER.debug("pair/request response: %s", result)

        auth_key = result.get("auth_key")
        timestamp = result.get("timestamp")
        if not auth_key or timestamp is None:
            raise PhilipsTVError(f"Invalid pair/request response: {result}")

        return str(auth_key), timestamp

    def pair_grant(self, pin: str, auth_key: str, timestamp: Any) -> tuple[str, str]:
        """
        Step 2: confirm PIN and receive credentials.

        Args:
            pin: PIN code shown on TV screen
            auth_key: hex string from pair/request response
            timestamp: timestamp from pair/request response (int or str)
        """
        signature = self._generate_signature(timestamp, pin)
        _LOGGER.debug(
            "pair/grant: auth_key_len=%d timestamp=%s pin=%s sig=%s",
            len(auth_key), timestamp, pin, signature,
        )
        payload = {
            "auth": {
                "auth_appId": "1",
                "pin": pin,
                "auth_timestamp": timestamp,
                "auth_signature": signature,
            },
            "device": {
                "app_id": PAIR_DEVICE_ID,
                "id": PAIR_DEVICE_ID,
                "device_name": PAIR_DEVICE_NAME,
                "type": "native",
                "app_name": PAIR_DEVICE_NAME,
            },
        }
        _LOGGER.debug("pair/grant payload: %s", payload)

        # pair/grant Digest Auth username is PAIR_DEVICE_ID, password is auth_key hex
        grant_auth = HTTPDigestAuth(PAIR_DEVICE_ID, auth_key)
        result = self._post("pair/grant", payload, auth=grant_auth)
        if not result:
            raise PhilipsTVError("Empty response from pair/grant")
        _LOGGER.debug("pair/grant response: %s", result)

        # Credentials returned are (PAIR_DEVICE_ID, auth_key)
        device = result.get("device", {})
        username = device.get("id") or PAIR_DEVICE_ID
        password = device.get("auth_key") or auth_key

        return username, password

    def _generate_signature(self, timestamp: Any, pin: str) -> str:
        """Generate HMAC-SHA1 signature using fixed AUTH_SHARED_KEY."""
        message = (str(timestamp) + str(pin)).encode("utf-8")
        h = hmac.new(AUTH_SHARED_KEY, message, hashlib.sha1)
        return base64.b64encode(h.digest()).decode()

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    def get_system_info(self) -> dict[str, Any]:
        """Get TV system information (model, api_version, etc.)."""
        return self._get("system")

    def is_online(self) -> bool:
        """Check if the TV is reachable."""
        try:
            self.get_system_info()
            return True
        except PhilipsTVError:
            return False

    # ------------------------------------------------------------------
    # Ambilight
    # ------------------------------------------------------------------

    def get_ambilight_topology(self) -> dict[str, Any]:
        """Get the ambilight topology (number of pixels per side)."""
        return self._get("ambilight/topology")

    def get_ambilight_processed(self) -> dict[str, Any]:
        """Get processed ambilight colors (post-processing, what LEDs show)."""
        return self._get("ambilight/processed")

    def get_ambilight_measured(self) -> dict[str, Any]:
        """Get measured ambilight colors (raw from screen image)."""
        return self._get("ambilight/measured")

    def get_ambilight_colors(self) -> dict[str, Any]:
        """
        Get live ambilight colors.
        Tries /ambilight/processed first; if all zero (e.g. physical LEDs are off),
        falls back to /ambilight/measured (video content on TV screen).
        """
        try:
            data = self.get_ambilight_processed()
            if data:
                colors = parse_ambilight_colors(data)
                if any(r > 0 or g > 0 or b > 0 for r, g, b in colors.values()):
                    return data
        except Exception:  # noqa: BLE001
            pass

        return self.get_ambilight_measured()

    def get_powerstate(self) -> str | None:
        """
        Get TV power state (e.g. 'On', 'Standby', 'Off').
        Returns None if TV does not support endpoint or is offline.
        """
        try:
            data = self._get("powerstate")
            if isinstance(data, dict):
                return data.get("powerstate")
        except PhilipsTVOfflineError:
            return "Off"
        except Exception as err:
            _LOGGER.debug("Failed to get powerstate: %s", err)
        return None

    def is_tv_on(self) -> bool:
        """
        Check if the TV is turned on (not in standby, off, or unreachable).
        """
        powerstate = self.get_powerstate()
        if powerstate:
            return powerstate.lower() == "on"

        # Fallback to ambilight/power if powerstate endpoint is not available
        try:
            amb_power = self.get_ambilight_power()
            if isinstance(amb_power, dict) and "power" in amb_power:
                return amb_power["power"].lower() == "on"
        except Exception:
            pass

        return self.is_online()

    def fetch_ambilight_state(self) -> dict[str, Any]:
        """
        Fetch ambilight colors and power status in a single executor call.
        Returns dict with:
          - 'online': bool
          - 'tv_on': bool
          - 'powerstate': str | None
          - 'raw_colors': dict | None
        """
        try:
            raw = self.get_ambilight_colors()
        except PhilipsTVOfflineError:
            return {"online": False, "tv_on": False, "powerstate": "Off", "raw_colors": None}
        except PhilipsTVError as err:
            _LOGGER.debug("Ambilight API error during fetch: %s", err)
            return {"online": False, "tv_on": False, "powerstate": "Unknown", "raw_colors": None}

        # Check if received colors are non-zero
        colors = parse_ambilight_colors(raw)
        has_active_color = any(r > 0 or g > 0 or b > 0 for r, g, b in colors.values())

        if has_active_color:
            # Active ambilight colors mean the screen is definitely displaying content
            return {"online": True, "tv_on": True, "powerstate": "On", "raw_colors": raw}

        # Colors are all zero: check if TV is actually on (black screen) or in Standby
        pstate = self.get_powerstate()
        if pstate:
            is_on = pstate.lower() == "on"
            return {"online": True, "tv_on": is_on, "powerstate": pstate, "raw_colors": raw}

        # Fallback to ambilight/power
        try:
            amb_power = self.get_ambilight_power()
            if isinstance(amb_power, dict) and "power" in amb_power:
                is_on = amb_power["power"].lower() == "on"
                return {
                    "online": True,
                    "tv_on": is_on,
                    "powerstate": "On" if is_on else "Standby",
                    "raw_colors": raw,
                }
        except Exception:
            pass

        # If we cannot determine power state and colors are all 0, assume TV is on black screen
        return {"online": True, "tv_on": True, "powerstate": "Unknown", "raw_colors": raw}

    def get_ambilight_power(self) -> dict[str, Any]:
        """Get ambilight power state."""
        return self._get("ambilight/power")

    def get_ambilight_mode(self) -> dict[str, Any]:
        """Get current ambilight mode."""
        return self._get("ambilight/mode")


def parse_ambilight_colors(
    data: dict[str, Any],
    sides: list[str] | None = None,
) -> dict[str, tuple[int, int, int]]:
    """
    Parse ambilight API response into per-side average RGB colors.

    Args:
        data: Response from /ambilight/processed or /ambilight/measured
        sides: Which sides to include (default: all found in data)

    Returns:
        Dict mapping side name → average (r, g, b)
    """
    result: dict[str, tuple[int, int, int]] = {}

    # Support both layer1 and flat structures
    layer = data.get("layer1", data)

    for side, pixels in layer.items():
        if sides and side not in sides:
            continue
        if not isinstance(pixels, dict):
            continue

        # Pixels can be {r, g, b} directly (single pixel)
        # or {"0": {r,g,b}, "1": {r,g,b}, ...} (multiple pixels)
        rgb_values = _extract_rgb_list(pixels)
        if rgb_values:
            avg_r = int(sum(c[0] for c in rgb_values) / len(rgb_values))
            avg_g = int(sum(c[1] for c in rgb_values) / len(rgb_values))
            avg_b = int(sum(c[2] for c in rgb_values) / len(rgb_values))
            result[side] = (avg_r, avg_g, avg_b)

    return result


def parse_ambilight_pixels(data: dict[str, Any]) -> dict[str, dict[str, tuple[int, int, int]]]:
    """Parse raw ambilight response into per-side, per-diode RGB dictionary."""
    result: dict[str, dict[str, tuple[int, int, int]]] = {}
    layer = data.get("layer1", data)

    for side, pixels in layer.items():
        if not isinstance(pixels, dict):
            continue
        side_pixels: dict[str, tuple[int, int, int]] = {}
        if "r" in pixels and "g" in pixels and "b" in pixels:
            side_pixels["0"] = (pixels["r"], pixels["g"], pixels["b"])
        else:
            for idx_str, p_val in pixels.items():
                if isinstance(p_val, dict) and "r" in p_val:
                    side_pixels[str(idx_str)] = (p_val["r"], p_val["g"], p_val["b"])
        if side_pixels:
            result[side] = side_pixels

    return result


def extract_corner_diodes(data: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    """Extract bottom-most diode RGB colors for left and right sides (index 0 is bottom)."""
    pixels = parse_ambilight_pixels(data)
    result: dict[str, tuple[int, int, int]] = {}

    # Left bottom diode (index "0" is at the bottom of left side)
    left_p = pixels.get("left", {})
    if left_p:
        sorted_keys = sorted(left_p.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)
        result["left_bottom"] = left_p[sorted_keys[0]]

    # Right bottom diode (index "0" is at the bottom of right side)
    right_p = pixels.get("right", {})
    if right_p:
        sorted_keys = sorted(right_p.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)
        result["right_bottom"] = right_p[sorted_keys[0]]

    return result


def _extract_rgb_list(pixels: dict) -> list[tuple[int, int, int]]:
    """Extract list of (r, g, b) tuples from pixel data."""
    # Case 1: direct {r, g, b}
    if "r" in pixels and "g" in pixels and "b" in pixels:
        return [(pixels["r"], pixels["g"], pixels["b"])]

    # Case 2: {"0": {r,g,b}, "1": {r,g,b}, ...}
    result = []
    for key, value in pixels.items():
        if isinstance(value, dict) and "r" in value:
            result.append((value["r"], value["g"], value["b"]))
    return result


def average_colors(
    side_colors: dict[str, tuple[int, int, int]],
    sides: list[str] | None = None,
) -> tuple[int, int, int]:
    """
    Compute a single average RGB color from multiple sides.

    Args:
        side_colors: Dict of side → (r, g, b)
        sides: Which sides to include (default: all)

    Returns:
        Average (r, g, b)
    """
    colors = [
        v for k, v in side_colors.items()
        if sides is None or k in sides
    ]
    if not colors:
        return (0, 0, 0)

    r = int(sum(c[0] for c in colors) / len(colors))
    g = int(sum(c[1] for c in colors) / len(colors))
    b = int(sum(c[2] for c in colors) / len(colors))
    return (r, g, b)
