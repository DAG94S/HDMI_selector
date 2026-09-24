"""Display and screensaver management using Win32 APIs and ctypes."""

import ctypes
from ctypes import wintypes
from enum import Enum
import logging

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

# QueryDisplayConfig flags and return codes
QDC_ONLY_ACTIVE_PATHS = 0x00000002
ERROR_SUCCESS = 0

# SystemParametersInfo flags and actions
SPI_SETSCREENSAVEACTIVE = 0x0011
SPI_SETSCREENSAVETIMEOUT = 0x000F
SPI_GETSCREENSAVEACTIVE = 0x0010
SPI_GETSCREENSAVETIMEOUT = 0x000E
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

# Output technology constants
OUTPUT_TECHNOLOGY_HDMI = 5

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

# External display technologies (monitors, projectors, TVs, external ports)
EXTERNAL_OUTPUT_TECHNOLOGIES = {
    0,   # VGA
    1,   # S-Video
    2,   # Composite
    3,   # Component
    4,   # DVI
    5,   # HDMI
    8,   # D-JPN
    9,   # SDI
    10,  # DisplayPort
    12,  # UDI external
    14,  # SDTV dongle
    15,  # Miracast
    16,  # Indirect wired (dock / DisplayLink)
    17,  # Indirect virtual
    18,  # DisplayPort USB tunneling
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


class DisplayManager:
    """Manages display topologies and screensaver settings via Win32 APIs."""

    def __init__(self, user32=None, winreg_module=None):
        if user32 is not None:
            self._user32 = user32
        elif hasattr(ctypes, "windll"):
            self._user32 = ctypes.windll.user32
        else:  # pragma: no cover
            self._user32 = None

        self._winreg = winreg_module if winreg_module is not None else winreg
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

    def get_active_display_technologies(self) -> list[int]:
        """Queries QueryDisplayConfig to retrieve active display output technologies."""
        if self._user32 is None:
            return []

        try:
            path_count = wintypes.UINT()
            mode_count = wintypes.UINT()
            res = self._user32.GetDisplayConfigBufferSizes(
                QDC_ONLY_ACTIVE_PATHS,
                ctypes.byref(path_count),
                ctypes.byref(mode_count),
            )
            if res != ERROR_SUCCESS:
                logger.warning("GetDisplayConfigBufferSizes failed with code: %s", res)
                return []

            if path_count.value == 0:
                return []

            paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
            modes = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()

            res = self._user32.QueryDisplayConfig(
                QDC_ONLY_ACTIVE_PATHS,
                ctypes.byref(path_count),
                paths,
                ctypes.byref(mode_count),
                modes,
                None,
            )
            if res != ERROR_SUCCESS:
                logger.warning("QueryDisplayConfig failed with code: %s", res)
                return []

            return [
                int(paths[i].targetInfo.outputTechnology)
                for i in range(path_count.value)
            ]
        except Exception as e:
            logger.error("Error querying display technologies: %s", e)
            return []

    def is_hdmi_connected(self, technologies: list[int] | None = None) -> bool:
        """Returns True if HDMI or any external monitor technology is connected/active."""
        if technologies is None:
            technologies = self.get_active_display_technologies()
        return any(
            t == OUTPUT_TECHNOLOGY_HDMI or t in EXTERNAL_OUTPUT_TECHNOLOGIES
            for t in technologies
        )

    def get_active_display_names(
        self, technologies: list[int] | None = None
    ) -> list[str]:
        """Maps technology integers to human-readable display names."""
        if technologies is None:
            technologies = self.get_active_display_technologies()
        return [
            OUTPUT_TECHNOLOGY_NAMES.get(t, f"Unknown ({t})") for t in technologies
        ]

    def set_display_topology(self, topology: int) -> bool:
        """Sets display topology using SetDisplayConfig."""
        if self._user32 is None:
            logger.error("user32 is unavailable")
            return False

        try:
            flags = SDC_APPLY | topology
            res = self._user32.SetDisplayConfig(0, None, 0, None, flags)
            if res == ERROR_SUCCESS:
                logger.info("SetDisplayConfig succeeded with topology 0x%08X", topology)
                return True
            logger.warning("SetDisplayConfig failed with code %s", res)
            return False
        except Exception as e:
            logger.error("Error setting display topology: %s", e)
            return False

    def set_screensaver(self, active: bool, timeout_seconds: int = 60) -> bool:
        """Sets screensaver activation and timeout via SystemParametersInfoW and registry."""
        flags = SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        spi_ok = False

        if self._user32 is not None:
            try:
                res1 = self._user32.SystemParametersInfoW(
                    SPI_SETSCREENSAVEACTIVE,
                    1 if active else 0,
                    None,
                    flags,
                )
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

    def apply_mode(self, mode: AppMode | str, timeout_seconds: int = 60) -> dict:
        """Applies configuration corresponding to the requested AppMode."""
        if isinstance(mode, str):
            try:
                mode = AppMode(mode)
            except ValueError:
                raise ValueError(f"Invalid mode: {mode}")

        if mode == AppMode.PRESENTATION:
            if not self.set_display_topology(SDC_TOPOLOGY_EXTERNAL):
                logger.warning(
                    "Failed to switch topology to external for presentation; "
                    "keeping screensaver active to protect OLED panel."
                )
                return {
                    "success": False,
                    "mode": mode,
                    "topology": None,
                    "screensaver": None,
                    "timeout": None,
                }
            ss_ok = self.set_screensaver(active=False)
            return {
                "success": bool(ss_ok),
                "mode": mode,
                "topology": "external",
                "screensaver": False if ss_ok else None,
                "timeout": None,
            }
        elif mode == AppMode.TEACHER:
            if not self.set_display_topology(SDC_TOPOLOGY_EXTEND):
                logger.warning("Failed to switch topology to extend for teacher mode.")
                return {
                    "success": False,
                    "mode": mode,
                    "topology": None,
                    "screensaver": None,
                    "timeout": None,
                }
            ss_ok = self.set_screensaver(active=False)
            return {
                "success": bool(ss_ok),
                "mode": mode,
                "topology": "extend",
                "screensaver": False if ss_ok else None,
                "timeout": None,
            }
        elif mode == AppMode.EXERCISES:
            if not self.set_display_topology(SDC_TOPOLOGY_EXTEND):
                logger.warning(
                    "Failed to switch topology to extend for exercises; "
                    "keeping screensaver active to protect OLED panel."
                )
                return {
                    "success": False,
                    "mode": mode,
                    "topology": None,
                    "screensaver": None,
                    "timeout": None,
                }
            ss_ok = self.set_screensaver(active=False)
            return {
                "success": bool(ss_ok),
                "mode": mode,
                "topology": "extend",
                "screensaver": False if ss_ok else None,
                "timeout": None,
            }
        elif mode == AppMode.NORMAL:
            top_ok = self.set_display_topology(SDC_TOPOLOGY_INTERNAL)
            ss_ok = self.set_screensaver(
                active=True, timeout_seconds=timeout_seconds
            )
            success = bool(top_ok and ss_ok)
            if not success:
                logger.warning(
                    "Failed to apply normal mode (top_ok=%s, ss_ok=%s)",
                    top_ok,
                    ss_ok,
                )
                return {
                    "success": False,
                    "mode": mode,
                    "topology": "internal" if top_ok else None,
                    "screensaver": True if ss_ok else None,
                    "timeout": timeout_seconds if ss_ok else None,
                }
            return {
                "success": True,
                "mode": mode,
                "topology": "internal",
                "screensaver": True,
                "timeout": timeout_seconds,
            }
        else:
            raise ValueError(f"Unsupported mode: {mode}")
