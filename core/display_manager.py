"""Display and screensaver management using Win32 APIs and ctypes."""

import ctypes
from ctypes import wintypes
from enum import Enum
import logging
import time
from typing import Callable, Optional

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

logger = logging.getLogger(__name__)


class AppMode(str, Enum):
    """Application operational modes."""
    PRESENTATION = "presentation"
    TEACHER = "teacher"
    EXERCISES = "exercises"
    NORMAL = "normal"


# Topology flags for SetDisplayConfig
SDC_TOPOLOGY_INTERNAL = 0x00000001
SDC_TOPOLOGY_CLONE = 0x00000002
SDC_TOPOLOGY_EXTEND = 0x00000004
SDC_TOPOLOGY_EXTERNAL = 0x00000008
SDC_APPLY = 0x00000080

# Topology names as reported by get_current_topology()
TOPOLOGY_INTERNAL = "internal"
TOPOLOGY_EXTERNAL = "external"
TOPOLOGY_EXTEND = "extend"
TOPOLOGY_CLONE = "clone"

TOPOLOGY_FLAG_NAMES = {
    SDC_TOPOLOGY_INTERNAL: TOPOLOGY_INTERNAL,
    SDC_TOPOLOGY_CLONE: TOPOLOGY_CLONE,
    SDC_TOPOLOGY_EXTEND: TOPOLOGY_EXTEND,
    SDC_TOPOLOGY_EXTERNAL: TOPOLOGY_EXTERNAL,
}

# QueryDisplayConfig flags and return codes
QDC_ALL_PATHS = 0x00000001
QDC_ONLY_ACTIVE_PATHS = 0x00000002
ERROR_SUCCESS = 0
ERROR_INSUFFICIENT_BUFFER = 122

# DISPLAYCONFIG path / mode constants
DISPLAYCONFIG_PATH_ACTIVE = 0x00000001
DISPLAYCONFIG_PATH_MODE_IDX_INVALID = 0xFFFFFFFF
DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1

# Retry / verification policy
QUERY_MAX_ATTEMPTS = 3
SET_TOPOLOGY_MAX_ATTEMPTS = 3
SET_TOPOLOGY_RETRY_DELAY = 0.5
TOPOLOGY_VERIFY_INTERVAL = 0.5
TOPOLOGY_VERIFY_POLLS = 6  # ~3 seconds

# SystemParametersInfo flags and actions
SPI_SETSCREENSAVEACTIVE = 0x0011
SPI_SETSCREENSAVETIMEOUT = 0x000F
SPI_GETSCREENSAVEACTIVE = 0x0010
SPI_GETSCREENSAVETIMEOUT = 0x000E
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

# Output technology constants
OUTPUT_TECHNOLOGY_HDMI = 5
OUTPUT_TECHNOLOGY_INTERNAL = -2147483648  # 0x80000000 as signed int

OUTPUT_TECHNOLOGY_NAMES = {
    -1: "Other",
    0: "VGA",
    1: "S-Video",
    2: "Composite",
    3: "Component",
    4: "DVI",
    5: "HDMI",
    6: "Internal/Laptop",
    8: "D-JPN",
    9: "SDI",
    10: "DisplayPort",
    11: "Internal DisplayPort",
    12: "External UDI",
    13: "Internal UDI",
    14: "SDTV Dongle",
    15: "Miracast",
    16: "Indirect Wired",
    17: "Indirect Virtual",
    18: "DisplayPort USB Tunneling",
    -2147483648: "Internal/Laptop",
    0x80000000: "Internal/Laptop",
}

# External display technologies (monitors, projectors, TVs, external ports).
# 17 (Indirect Virtual: virtual display drivers, remote sessions, etc.) is NOT a
# physical external display and is excluded so it never counts as "HDMI connected".
EXTERNAL_OUTPUT_TECHNOLOGIES = {
    0,   # VGA (HD15)
    1,   # S-Video
    2,   # Composite
    3,   # Component
    4,   # DVI
    5,   # HDMI
    8,   # D-JPN
    9,   # SDI
    10,  # DisplayPort external
    12,  # UDI external
    14,  # SDTV dongle
    15,  # Miracast (wireless projector / TV)
    16,  # Indirect wired (dock / DisplayLink)
    18,  # DisplayPort USB tunneling (USB-C / Thunderbolt)
}

# Built-in panel technologies (laptop display)
INTERNAL_OUTPUT_TECHNOLOGIES = {
    6,            # LVDS
    11,           # Embedded DisplayPort (eDP)
    13,           # Embedded UDI
    -2147483648,  # DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL (signed)
    0x80000000,   # DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL (unsigned)
}


# Win32 ctypes structures for QueryDisplayConfig
class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [
        ("Numerator", wintypes.UINT),
        ("Denominator", wintypes.UINT),
    ]


class DISPLAYCONFIG_2DREGION(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.UINT),
        ("cy", wintypes.UINT),
    ]


class DISPLAYCONFIG_VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [
        ("pixelRate", ctypes.c_uint64),
        ("hSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("vSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("activeSize", DISPLAYCONFIG_2DREGION),
        ("totalSize", DISPLAYCONFIG_2DREGION),
        ("videoStandard", wintypes.UINT),
        ("scanLineOrdering", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", ctypes.c_int),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class POINTL(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class DISPLAYCONFIG_SOURCE_MODE(ctypes.Structure):
    _fields_ = [
        ("width", wintypes.UINT),
        ("height", wintypes.UINT),
        ("pixelFormat", wintypes.UINT),
        ("position", POINTL),
    ]


class DISPLAYCONFIG_TARGET_MODE(ctypes.Structure):
    _fields_ = [
        ("targetVideoSignalInfo", DISPLAYCONFIG_VIDEO_SIGNAL_INFO),
    ]


class DISPLAYCONFIG_MODE_INFO_UNION(ctypes.Union):
    _fields_ = [
        ("targetMode", DISPLAYCONFIG_TARGET_MODE),
        ("sourceMode", DISPLAYCONFIG_SOURCE_MODE),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("infoType", wintypes.UINT),
        ("id", wintypes.UINT),
        ("adapterId", LUID),
        ("modeInfo", DISPLAYCONFIG_MODE_INFO_UNION),
    ]



class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", LUID),
        ("id", wintypes.UINT),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", wintypes.WCHAR * 32),
    ]


# Mode associated with each detected topology (TEACHER cannot be distinguished
# from EXERCISES at the topology level; the UI decides using its config).
TOPOLOGY_TO_MODE = {
    TOPOLOGY_INTERNAL: AppMode.NORMAL,
    TOPOLOGY_EXTERNAL: AppMode.PRESENTATION,
    TOPOLOGY_EXTEND: AppMode.EXERCISES,
}


def _luid_key(luid: LUID) -> tuple[int, int]:
    """Returns a hashable key for a LUID structure."""
    return (int(luid.LowPart), int(luid.HighPart))


class DisplayManager:
    """Manages display topologies and screensaver settings via Win32 APIs."""

    def __init__(
        self,
        user32=None,
        winreg_module=None,
        sleep_func: Optional[Callable[[float], None]] = None,
    ):
        """Initializes DisplayManager.

        Args:
            user32: Optional user32 DLL (or mock). Defaults to ctypes.windll.user32.
            winreg_module: Optional winreg module (or mock).
            sleep_func: Optional sleep function used between retries / verification
                polls (injectable so tests run instantly). Defaults to time.sleep.
        """
        if user32 is not None:
            self._user32 = user32
        elif hasattr(ctypes, "windll"):
            self._user32 = ctypes.windll.user32
        else:  # pragma: no cover
            self._user32 = None

        self._winreg = winreg_module if winreg_module is not None else winreg
        self._sleep: Callable[[float], None] = sleep_func if sleep_func is not None else time.sleep
        self._setup_api_signatures()

    def _setup_api_signatures(self) -> None:
        """Configures explicit ctypes argtypes and restype for Win32 API functions."""
        if self._user32 is None:
            return

        try:
            if hasattr(self._user32, "GetDisplayConfigBufferSizes"):
                self._user32.GetDisplayConfigBufferSizes.argtypes = [
                    wintypes.UINT,
                    ctypes.POINTER(wintypes.UINT),
                    ctypes.POINTER(wintypes.UINT),
                ]
                self._user32.GetDisplayConfigBufferSizes.restype = wintypes.LONG

            if hasattr(self._user32, "QueryDisplayConfig"):
                self._user32.QueryDisplayConfig.argtypes = [
                    wintypes.UINT,
                    ctypes.POINTER(wintypes.UINT),
                    ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
                    ctypes.POINTER(wintypes.UINT),
                    ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
                    ctypes.c_void_p,
                ]
                self._user32.QueryDisplayConfig.restype = wintypes.LONG

            if hasattr(self._user32, "SetDisplayConfig"):
                self._user32.SetDisplayConfig.argtypes = [
                    wintypes.UINT,
                    ctypes.c_void_p,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    wintypes.UINT,
                ]
                self._user32.SetDisplayConfig.restype = wintypes.LONG

            if hasattr(self._user32, "DisplayConfigGetDeviceInfo"):
                self._user32.DisplayConfigGetDeviceInfo.argtypes = [
                    ctypes.POINTER(DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ]
                self._user32.DisplayConfigGetDeviceInfo.restype = wintypes.LONG

            if hasattr(self._user32, "SystemParametersInfoW"):
                self._user32.SystemParametersInfoW.argtypes = [
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    wintypes.UINT,
                ]
                self._user32.SystemParametersInfoW.restype = wintypes.BOOL
        except Exception as e:
            logger.debug("Failed to configure API signatures: %s", e)

    # ------------------------------------------------------------------
    # QueryDisplayConfig helpers
    # ------------------------------------------------------------------

    def _query_display_config(
        self, flags: int
    ) -> Optional[tuple[list[DISPLAYCONFIG_PATH_INFO], list[DISPLAYCONFIG_MODE_INFO]]]:
        """Runs GetDisplayConfigBufferSizes + QueryDisplayConfig.

        Retries when the configuration changes between both calls
        (ERROR_INSUFFICIENT_BUFFER), which is common during a topology switch.

        Returns:
            (paths, modes) on success (possibly empty lists), or None if the API
            failed and the display state is unknown.
        """
        if self._user32 is None:
            return None

        try:
            for attempt in range(1, QUERY_MAX_ATTEMPTS + 1):
                path_count = wintypes.UINT()
                mode_count = wintypes.UINT()
                res = self._user32.GetDisplayConfigBufferSizes(
                    flags,
                    ctypes.byref(path_count),
                    ctypes.byref(mode_count),
                )
                if res == ERROR_INSUFFICIENT_BUFFER:
                    logger.debug(
                        "GetDisplayConfigBufferSizes returned ERROR_INSUFFICIENT_BUFFER "
                        "(attempt %d/%d)", attempt, QUERY_MAX_ATTEMPTS,
                    )
                    continue
                if res != ERROR_SUCCESS:
                    logger.warning("GetDisplayConfigBufferSizes failed with code: %s", res)
                    return None

                if path_count.value == 0:
                    return [], []

                paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
                modes = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()

                res = self._user32.QueryDisplayConfig(
                    flags,
                    ctypes.byref(path_count),
                    paths,
                    ctypes.byref(mode_count),
                    modes,
                    None,
                )
                if res == ERROR_INSUFFICIENT_BUFFER:
                    logger.debug(
                        "QueryDisplayConfig returned ERROR_INSUFFICIENT_BUFFER "
                        "(attempt %d/%d); display configuration changed, retrying",
                        attempt, QUERY_MAX_ATTEMPTS,
                    )
                    continue
                if res != ERROR_SUCCESS:
                    logger.warning("QueryDisplayConfig failed with code: %s", res)
                    return None

                n_paths = min(int(path_count.value), len(paths))
                n_modes = min(int(mode_count.value), len(modes))
                return (
                    [paths[i] for i in range(n_paths)],
                    [modes[i] for i in range(n_modes)],
                )

            logger.warning(
                "QueryDisplayConfig kept returning ERROR_INSUFFICIENT_BUFFER after %d attempts",
                QUERY_MAX_ATTEMPTS,
            )
            return None
        except Exception as e:
            logger.error("Error querying display configuration: %s", e)
            return None

    @staticmethod
    def _target_key(path: DISPLAYCONFIG_PATH_INFO) -> tuple[int, int, int]:
        """Unique key of a path target (adapter LUID + target id)."""
        return _luid_key(path.targetInfo.adapterId) + (int(path.targetInfo.id),)

    @staticmethod
    def _source_key(path: DISPLAYCONFIG_PATH_INFO) -> tuple[int, int, int]:
        """Unique key of a path source (adapter LUID + source id)."""
        return _luid_key(path.sourceInfo.adapterId) + (int(path.sourceInfo.id),)

    # ------------------------------------------------------------------
    # Display detection
    # ------------------------------------------------------------------

    def get_active_display_technologies(self) -> list[int]:
        """Returns output technologies of ACTIVE display paths ([] on error)."""
        result = self._query_display_config(QDC_ONLY_ACTIVE_PATHS)
        if result is None:
            return []
        paths, _modes = result
        return [int(p.targetInfo.outputTechnology) for p in paths]

    def get_available_external_technologies(self) -> Optional[list[int]]:
        """Returns technologies of external targets that are physically available.

        Uses QDC_ALL_PATHS + targetInfo.targetAvailable, so an external display that is
        connected but inactive (e.g. NORMAL / internal-only topology) is still reported.
        Targets are de-duplicated by adapter + target id.

        Returns:
            List of output technologies (one per available external target), or None
            if the display configuration could not be queried (unknown state).
        """
        result = self._query_display_config(QDC_ALL_PATHS)
        if result is None:
            return None
        paths, _modes = result
        if not paths:
            # Every system has at least one path; zero paths means a transient state.
            logger.debug("QueryDisplayConfig(QDC_ALL_PATHS) returned no paths; state unknown")
            return None

        seen: set[tuple[int, int, int]] = set()
        technologies: list[int] = []
        for p in paths:
            if not p.targetInfo.targetAvailable:
                continue
            tech = int(p.targetInfo.outputTechnology)
            if tech not in EXTERNAL_OUTPUT_TECHNOLOGIES:
                continue
            key = self._target_key(p)
            if key in seen:
                continue
            seen.add(key)
            technologies.append(tech)
        return technologies

    def is_hdmi_connected(self, technologies: list[int] | None = None) -> Optional[bool]:
        """Returns whether an HDMI / external display is connected.

        Args:
            technologies: Optional explicit list of output technologies to evaluate.
                When omitted, the system is queried for AVAILABLE external targets
                (connected even if inactive).

        Returns:
            True/False, or None if the state could not be determined (API error).
            Callers must treat None as "unknown", never as "disconnected".
        """
        if technologies is not None:
            return any(t in EXTERNAL_OUTPUT_TECHNOLOGIES for t in technologies)
        available = self.get_available_external_technologies()
        if available is None:
            return None
        return len(available) > 0

    def get_active_display_names(
        self, technologies: list[int] | None = None
    ) -> list[str]:
        """Maps technology integers of ACTIVE displays to human-readable names."""
        if technologies is None:
            technologies = self.get_active_display_technologies()
        return [
            OUTPUT_TECHNOLOGY_NAMES.get(t, f"Unknown ({t})") for t in technologies
        ]

    def get_current_topology(self) -> Optional[str]:
        """Derives the current topology from the ACTIVE display paths.

        Returns:
            "internal" if only internal panels are active, "external" if only external
            displays are active, "extend" if 2+ targets are active with distinct sources,
            "clone" if 2+ targets share a source, or None if it cannot be determined.
        """
        result = self._query_display_config(QDC_ONLY_ACTIVE_PATHS)
        if result is None:
            return None
        paths, _modes = result
        if not paths:
            return None

        targets: dict[tuple[int, int, int], tuple[int, tuple[int, int, int]]] = {}
        for p in paths:
            targets.setdefault(
                self._target_key(p),
                (int(p.targetInfo.outputTechnology), self._source_key(p)),
            )

        has_internal = any(t in INTERNAL_OUTPUT_TECHNOLOGIES for t, _ in targets.values())
        has_external = any(t not in INTERNAL_OUTPUT_TECHNOLOGIES for t, _ in targets.values())

        if has_internal and not has_external:
            return TOPOLOGY_INTERNAL
        if has_external and not has_internal:
            return TOPOLOGY_EXTERNAL

        sources = {src for _, src in targets.values()}
        if len(sources) < len(targets):
            return TOPOLOGY_CLONE
        return TOPOLOGY_EXTEND

    def detect_current_mode(self) -> Optional[AppMode]:
        """Maps the current topology to an AppMode.

        internal -> NORMAL, external -> PRESENTATION, extend -> EXERCISES (the UI decides
        whether it is actually TEACHER). Returns None if unknown (or clone topology).
        """
        topology = self.get_current_topology()
        if topology is None:
            return None
        return TOPOLOGY_TO_MODE.get(topology)

    def get_internal_display_device_names(self) -> Optional[list[str]]:
        """Returns the GDI device names (e.g. '\\\\.\\DISPLAY1') of ACTIVE internal panels.

        The names match MONITORINFOEXW.szDevice from GetMonitorInfoW, which allows the
        OLED curtain to identify the laptop monitor independently of DPI virtualization.

        Returns:
            List of device names ([] if no internal panel is active), or None if the
            display configuration could not be queried.
        """
        result = self._query_display_config(QDC_ONLY_ACTIVE_PATHS)
        if result is None:
            return None
        paths, _modes = result
        if self._user32 is None or not hasattr(self._user32, "DisplayConfigGetDeviceInfo"):
            return None

        names: list[str] = []
        for p in paths:
            if int(p.targetInfo.outputTechnology) not in INTERNAL_OUTPUT_TECHNOLOGIES:
                continue
            try:
                info = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
                info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
                info.header.size = ctypes.sizeof(DISPLAYCONFIG_SOURCE_DEVICE_NAME)
                info.header.adapterId = p.sourceInfo.adapterId
                info.header.id = p.sourceInfo.id
                res = self._user32.DisplayConfigGetDeviceInfo(ctypes.byref(info.header))
                if res != ERROR_SUCCESS:
                    logger.debug("DisplayConfigGetDeviceInfo(source name) failed: %s", res)
                    continue
                name = str(info.viewGdiDeviceName)
                if name and name not in names:
                    names.append(name)
            except Exception as e:
                logger.debug("Error reading internal display device name: %s", e)
        return names

    # ------------------------------------------------------------------
    # Topology control
    # ------------------------------------------------------------------

    def set_display_topology(self, topology: int) -> bool:
        """Sets display topology using SetDisplayConfig, with retries and verification.

        Tries up to SET_TOPOLOGY_MAX_ATTEMPTS times (pausing SET_TOPOLOGY_RETRY_DELAY
        seconds between failures) and then polls get_current_topology() for up to
        ~3 seconds to verify the requested topology is in effect. This call blocks and
        must not run on the Tk thread.

        Returns:
            True if SetDisplayConfig succeeded and the topology was verified (or could not
            be read back), False otherwise.
        """
        if self._user32 is None:
            logger.error("user32 is unavailable")
            return False

        flags = SDC_APPLY | topology
        applied = False
        for attempt in range(1, SET_TOPOLOGY_MAX_ATTEMPTS + 1):
            try:
                res = self._user32.SetDisplayConfig(0, None, 0, None, flags)
            except Exception as e:
                logger.error("Error setting display topology (attempt %d/%d): %s",
                             attempt, SET_TOPOLOGY_MAX_ATTEMPTS, e)
                res = None
            if res == ERROR_SUCCESS:
                applied = True
                logger.info(
                    "SetDisplayConfig succeeded with topology 0x%08X (attempt %d)",
                    topology, attempt,
                )
                break
            if res is not None:
                logger.warning(
                    "SetDisplayConfig failed with code %s (attempt %d/%d, topology 0x%08X)",
                    res, attempt, SET_TOPOLOGY_MAX_ATTEMPTS, topology,
                )
            if attempt < SET_TOPOLOGY_MAX_ATTEMPTS:
                self._sleep(SET_TOPOLOGY_RETRY_DELAY)

        if not applied:
            return False
        return self._verify_topology(topology)

    def _verify_topology(self, topology: int) -> bool:
        """Polls get_current_topology() until it matches the requested topology flag."""
        expected = TOPOLOGY_FLAG_NAMES.get(topology)
        if expected is None:
            return True

        last_seen: Optional[str] = None
        for poll in range(TOPOLOGY_VERIFY_POLLS):
            current = self.get_current_topology()
            if current == expected:
                logger.debug("Topology '%s' verified after %d poll(s)", expected, poll + 1)
                return True
            if current is not None:
                last_seen = current
            if poll < TOPOLOGY_VERIFY_POLLS - 1:
                self._sleep(TOPOLOGY_VERIFY_INTERVAL)

        if last_seen is None:
            logger.warning(
                "Could not read back display topology to verify '%s'; assuming success", expected
            )
            return True
        logger.warning(
            "Topology verification failed: expected '%s' but system reports '%s'",
            expected, last_seen,
        )
        return False

    # ------------------------------------------------------------------
    # Screensaver
    # ------------------------------------------------------------------

    def set_screensaver(self, active: bool, timeout_seconds: Optional[int] = None) -> bool:
        """Sets screensaver activation (and optionally timeout) via SPI and registry.

        Args:
            active: Whether the screensaver must be enabled.
            timeout_seconds: New timeout in seconds. If None, the current timeout is left
                untouched (only the active flag is toggled), preserving the user's value.
        """
        flags = SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        spi_ok = False
        set_timeout = timeout_seconds is not None

        if self._user32 is not None:
            try:
                res1 = self._user32.SystemParametersInfoW(
                    SPI_SETSCREENSAVEACTIVE,
                    1 if active else 0,
                    None,
                    flags,
                )
                res2 = True
                if set_timeout:
                    res2 = self._user32.SystemParametersInfoW(
                        SPI_SETSCREENSAVETIMEOUT,
                        int(timeout_seconds),
                        None,
                        flags,
                    )
                spi_ok = bool(res1 and res2)
            except Exception as e:
                logger.warning("SystemParametersInfoW error: %s", e)
                spi_ok = False
        else:
            logger.warning("user32 is not available for set_screensaver")

        reg_ok = False
        if self._winreg is not None:
            try:
                with self._winreg.OpenKey(
                    self._winreg.HKEY_CURRENT_USER,
                    r"Control Panel\Desktop",
                    0,
                    self._winreg.KEY_SET_VALUE,
                ) as key:
                    self._winreg.SetValueEx(
                        key,
                        "ScreenSaveActive",
                        0,
                        self._winreg.REG_SZ,
                        "1" if active else "0",
                    )
                    if set_timeout:
                        self._winreg.SetValueEx(
                            key,
                            "ScreenSaveTimeOut",
                            0,
                            self._winreg.REG_SZ,
                            str(int(timeout_seconds)),
                        )
                reg_ok = True
            except Exception as e:
                logger.warning("Registry update warning (non-fatal): %s", e)
                reg_ok = False
        else:
            reg_ok = False

        # Treat spi_ok as primary indicator; fall back to reg_ok if SPI unavailable
        return bool(spi_ok or reg_ok)

    def get_screensaver_state(self) -> dict:
        """Retrieves screensaver state (active and timeout in seconds)."""
        active = False
        timeout = 60

        # Try registry first (persistent user configuration)
        if self._winreg is not None:
            try:
                with self._winreg.OpenKey(
                    self._winreg.HKEY_CURRENT_USER,
                    r"Control Panel\Desktop",
                    0,
                    self._winreg.KEY_READ,
                ) as key:
                    val, _ = self._winreg.QueryValueEx(key, "ScreenSaveActive")
                    active = str(val).strip() == "1"
                    tval, _ = self._winreg.QueryValueEx(key, "ScreenSaveTimeOut")
                    timeout = int(tval)
                    return {"active": active, "timeout": timeout}
            except Exception:
                pass

        # Fallback to SystemParametersInfoW
        if self._user32 is not None:
            try:
                active_val = wintypes.BOOL()
                timeout_val = wintypes.UINT()
                r1 = self._user32.SystemParametersInfoW(
                    SPI_GETSCREENSAVEACTIVE, 0, ctypes.byref(active_val), 0
                )
                r2 = self._user32.SystemParametersInfoW(
                    SPI_GETSCREENSAVETIMEOUT, 0, ctypes.byref(timeout_val), 0
                )
                if r1:
                    active = bool(active_val.value)
                if r2:
                    timeout = int(timeout_val.value)
            except Exception:
                pass

        return {"active": active, "timeout": timeout}

    # ------------------------------------------------------------------
    # Modes
    # ------------------------------------------------------------------

    def apply_mode(self, mode: AppMode | str, timeout_seconds: int = 60) -> dict:
        """Applies configuration corresponding to the requested AppMode.

        Blocks while the topology is switched and verified (several seconds worst case).

        Returns:
            dict with keys: success (== topology_ok), mode, topology, screensaver, timeout,
            topology_ok, screensaver_ok. A screensaver failure is reported through
            screensaver_ok=False but does not make success False.
        """
        if isinstance(mode, str):
            try:
                mode = AppMode(mode)
            except ValueError:
                raise ValueError(f"Invalid mode: {mode}")

        if mode == AppMode.NORMAL:
            try:
                timeout_seconds = int(timeout_seconds)
            except (TypeError, ValueError):
                timeout_seconds = 0
            if timeout_seconds <= 0:
                logger.warning("Invalid screensaver timeout; falling back to 60 seconds")
                timeout_seconds = 60

            top_ok = bool(self.set_display_topology(SDC_TOPOLOGY_INTERNAL))
            # Always (re)enable the screensaver in NORMAL mode to protect the OLED panel.
            ss_ok = bool(self.set_screensaver(active=True, timeout_seconds=timeout_seconds))
            if not (top_ok and ss_ok):
                logger.warning(
                    "Normal mode applied with issues (top_ok=%s, ss_ok=%s)", top_ok, ss_ok
                )
            return {
                "success": top_ok,
                "mode": mode,
                "topology": TOPOLOGY_INTERNAL if top_ok else None,
                "screensaver": True if ss_ok else None,
                "timeout": timeout_seconds if ss_ok else None,
                "topology_ok": top_ok,
                "screensaver_ok": ss_ok,
            }

        if mode == AppMode.PRESENTATION:
            topology_flag = SDC_TOPOLOGY_EXTERNAL
        elif mode in (AppMode.TEACHER, AppMode.EXERCISES):
            # Teacher mode must never use EXTERNAL (Windows collapses all windows).
            topology_flag = SDC_TOPOLOGY_EXTEND
        else:  # pragma: no cover - exhaustive enum
            raise ValueError(f"Unsupported mode: {mode}")
        topology_name = TOPOLOGY_FLAG_NAMES[topology_flag]

        if not self.set_display_topology(topology_flag):
            logger.warning(
                "Failed to switch topology to %s for %s mode; "
                "keeping screensaver active to protect OLED panel.",
                topology_name,
                mode.value,
            )
            return {
                "success": False,
                "mode": mode,
                "topology": None,
                "screensaver": None,
                "timeout": None,
                "topology_ok": False,
                "screensaver_ok": False,
            }

        # Only toggle the active flag; keep the user's timeout value intact.
        ss_ok = bool(self.set_screensaver(active=False))
        if not ss_ok:
            logger.warning("Topology applied for %s mode but screensaver could not be disabled",
                           mode.value)
        return {
            "success": True,
            "mode": mode,
            "topology": topology_name,
            "screensaver": False if ss_ok else None,
            "timeout": None,
            "topology_ok": True,
            "screensaver_ok": ss_ok,
        }
