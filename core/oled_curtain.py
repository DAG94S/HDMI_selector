"""OLED blackout curtain service with monitor-scoped cursor tracking."""

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Win32 structures
class RECT(ctypes.Structure):
    """Win32 RECT structure."""
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    """Win32 POINT structure."""
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    """Win32 MONITORINFO structure."""
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# Safe 64-bit WNDPROC definition
WNDPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    """Win32 WNDCLASSW structure."""
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


# Win32 Constants
MONITOR_DEFAULTTOPRIMARY = 1
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000

SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNOACTIVATE = 4

HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080

PM_REMOVE = 0x0001
BLACK_BRUSH = 4

_WNDPROC_HOLDER: Optional[WNDPROC] = None


def _setup_api_signatures(user32) -> None:
    """Configures ctypes argument and return types for user32 APIs on 64-bit Windows."""
    if user32 is None or getattr(user32, "_signatures_configured", False):
        return
    try:
        # Only configure real ctypes functions, not Mock objects
        if hasattr(user32, "CreateWindowExW") and not getattr(user32.CreateWindowExW, "_mock_name", None):
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                wintypes.HMENU,
                wintypes.HINSTANCE,
                wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND

        if hasattr(user32, "DefWindowProcW") and not getattr(user32.DefWindowProcW, "_mock_name", None):
            user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = wintypes.LPARAM

        if hasattr(user32, "ShowWindow") and not getattr(user32.ShowWindow, "_mock_name", None):
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL

        if hasattr(user32, "ShowWindowAsync") and not getattr(user32.ShowWindowAsync, "_mock_name", None):
            user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindowAsync.restype = wintypes.BOOL

        if hasattr(user32, "DestroyWindow") and not getattr(user32.DestroyWindow, "_mock_name", None):
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL

        if hasattr(user32, "SetWindowPos") and not getattr(user32.SetWindowPos, "_mock_name", None):
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

        if hasattr(user32, "GetCursorPos") and not getattr(user32.GetCursorPos, "_mock_name", None):
            user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL

        if hasattr(user32, "MonitorFromPoint") and not getattr(user32.MonitorFromPoint, "_mock_name", None):
            user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HMONITOR

        if hasattr(user32, "GetMonitorInfoW") and not getattr(user32.GetMonitorInfoW, "_mock_name", None):
            user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL

        if hasattr(user32, "RegisterClassW") and not getattr(user32.RegisterClassW, "_mock_name", None):
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.ATOM

        kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
        if kernel32 and hasattr(kernel32, "GetModuleHandleW") and not getattr(kernel32.GetModuleHandleW, "_mock_name", None):
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        gdi32 = getattr(getattr(ctypes, "windll", None), "gdi32", None)
        if gdi32 and hasattr(gdi32, "GetStockObject") and not getattr(gdi32.GetStockObject, "_mock_name", None):
            gdi32.GetStockObject.argtypes = [ctypes.c_int]
            gdi32.GetStockObject.restype = wintypes.HBRUSH

        try:
            setattr(user32, "_signatures_configured", True)
        except Exception:
            pass
    except Exception as e:
        logger.debug("Failed to setup ctypes API signatures for user32: %s", e)


def get_primary_monitor_rect(user32=None) -> tuple[int, int, int, int]:
    """Retrieves the bounding rectangle (left, top, right, bottom) of the primary display.

    Uses Win32 MonitorFromPoint and GetMonitorInfoW, falling back to GetSystemMetrics,
    or a default 1920x1080 resolution if APIs are unavailable.
    """
    if user32 is None and hasattr(ctypes, "windll"):
        user32 = getattr(ctypes.windll, "user32", None)

    if user32 is not None:
        _setup_api_signatures(user32)
        try:
            pt = POINT(0, 0)
            if hasattr(user32, "MonitorFromPoint"):
                hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)
                if hmon:
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    if hasattr(user32, "GetMonitorInfoW") and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                        rc = mi.rcMonitor
                        return (int(rc.left), int(rc.top), int(rc.right), int(rc.bottom))
        except Exception as e:
            logger.debug("Win32 MonitorFromPoint/GetMonitorInfoW failed: %s", e)

        # Fallback to GetSystemMetrics
        try:
            if hasattr(user32, "GetSystemMetrics"):
                w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
                h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
                if w > 0 and h > 0:
                    return (0, 0, int(w), int(h))
        except Exception as e:
            logger.debug("Win32 GetSystemMetrics failed: %s", e)

    return (0, 0, 1920, 1080)


def is_point_in_primary_monitor(
    x: int,
    y: int,
    rect: Optional[tuple[int, int, int, int]] = None,
    user32=None,
) -> bool:
    """Returns True if (x, y) coordinates fall within primary monitor bounds.

    Bounds condition: left <= x < right and top <= y < bottom.
    """
    if rect is None:
        rect = get_primary_monitor_rect(user32=user32)
    left, top, right, bottom = rect
    return left <= x < right and top <= y < bottom


class OledCurtain:
    """Manages an OLED blackout curtain window and monitor-scoped cursor tracking.

    In Teacher Mode, this keeps the primary laptop display turned off (#000000)
    during inactivity while extended desktop presentation continues on the external display.
    Moving the cursor inside the laptop display instantly wakes it up; moving the cursor
    on the external display keeps the laptop display blacked out.
    """

    def __init__(
        self,
        timeout_seconds: int = 30,
        on_state_change: Optional[Callable[[bool], None]] = None,
        poll_interval: float = 0.05,
        user32=None,
    ) -> None:
        """Initializes OledCurtain service.

        Args:
            timeout_seconds: Seconds of inactivity on primary monitor before blackout.
            on_state_change: Callback invoked with is_blacked_out (bool) on state transition.
            poll_interval: Polling frequency in seconds for cursor checking.
            user32: Optional Win32 user32 DLL or mock.
        """
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {timeout_seconds}")
        if poll_interval <= 0:
            raise ValueError(f"poll_interval must be positive, got {poll_interval}")

        self._timeout_seconds = int(timeout_seconds)
        self._poll_interval = float(poll_interval)
        self.on_state_change = on_state_change

        if user32 is not None:
            self._user32 = user32
        elif hasattr(ctypes, "windll"):
            self._user32 = getattr(ctypes.windll, "user32", None)
        else:
            self._user32 = None

        _setup_api_signatures(self._user32)

        self._is_blacked_out = False
        self._last_cursor_pos: Optional[tuple[int, int]] = None
        self._last_activity_time: float = time.time()

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._hwnd: Optional[int] = None
        self._class_atom: Optional[int] = None

    @property
    def timeout_seconds(self) -> int:
        """Timeout in seconds before blackout."""
        with self._lock:
            return self._timeout_seconds

    @timeout_seconds.setter
    def timeout_seconds(self, value: int) -> None:
        val = int(value)
        if val <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {value}")
        with self._lock:
            self._timeout_seconds = val

    @property
    def poll_interval(self) -> float:
        """Interval between cursor polling iterations in seconds."""
        with self._lock:
            return self._poll_interval

    @poll_interval.setter
    def poll_interval(self, value: float) -> None:
        val = float(value)
        if val <= 0:
            raise ValueError(f"poll_interval must be positive, got {value}")
        with self._lock:
            self._poll_interval = val

    @property
    def last_activity_time(self) -> float:
        """Timestamp of last recorded user activity on primary monitor."""
        with self._lock:
            return self._last_activity_time

    def get_primary_monitor_rect(self) -> tuple[int, int, int, int]:
        """Returns the bounding rectangle of the primary display (left, top, right, bottom)."""
        return get_primary_monitor_rect(user32=self._user32)

    def is_point_in_primary_monitor(self, x: int, y: int) -> bool:
        """Returns True if the point (x, y) lies inside the primary monitor rect."""
        return is_point_in_primary_monitor(x, y, rect=self.get_primary_monitor_rect(), user32=self._user32)

    def get_cursor_pos(self) -> Optional[tuple[int, int]]:
        """Queries current cursor coordinates via Win32 GetCursorPos."""
        user32 = self._user32
        if user32 is None:
            return None
        try:
            pt = POINT()
            if hasattr(user32, "GetCursorPos") and user32.GetCursorPos(ctypes.byref(pt)):
                return (int(pt.x), int(pt.y))
        except Exception as e:
            logger.debug("GetCursorPos error: %s", e)
        return None

    def is_blacked_out(self) -> bool:
        """Returns whether the OLED blackout curtain is currently displayed."""
        with self._lock:
            return self._is_blacked_out

    def is_running(self) -> bool:
        """Returns whether the background cursor polling thread is active."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def wake(self, now: Optional[float] = None) -> None:
        """Hides the blackout window and notifies state change."""
        if now is None:
            now = time.time()
        callback = None
        with self._lock:
            self._last_activity_time = now
            if not self._is_blacked_out:
                return
            self._is_blacked_out = False
            self._hide_window()
            callback = self.on_state_change

        if callback is not None:
            try:
                callback(False)
            except Exception as e:
                logger.exception("Error in on_state_change callback during wake: %s", e)

    def blackout(self) -> None:
        """Shows the blackout window and notifies state change."""
        callback = None
        with self._lock:
            if self._is_blacked_out:
                return
            self._is_blacked_out = True
            self._show_window()
            callback = self.on_state_change

        if callback is not None:
            try:
                callback(True)
            except Exception as e:
                logger.exception("Error in on_state_change callback during blackout: %s", e)

    def start(self) -> None:
        """Initializes blackout window and starts cursor polling daemon thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("OledCurtain polling thread is already running.")
                return

            self._stop_event.clear()
            self._ready_event.clear()
            self._last_activity_time = time.time()
            self._last_cursor_pos = self.get_cursor_pos()

            self._thread = threading.Thread(
                target=self._run,
                name="OledCurtainThread",
                daemon=True,
            )
            self._thread.start()

        # Wait for worker thread to finish creating window before returning
        self._ready_event.wait(timeout=2.0)
        logger.info("OledCurtain started with timeout=%ds, poll_interval=%.2fs", self._timeout_seconds, self._poll_interval)

    def stop(self, timeout: float = 2.0) -> None:
        """Destroys blackout window and cleanly stops background polling thread."""
        callback = None
        with self._lock:
            was_blacked_out = self._is_blacked_out
            self._is_blacked_out = False
            if was_blacked_out:
                callback = self.on_state_change

            self._stop_event.set()
            thread = self._thread
            self._thread = None

        if thread is not None and thread.is_alive():
            if threading.current_thread() != thread:
                thread.join(timeout=timeout)
                if thread.is_alive():
                    logger.warning("OledCurtain thread did not stop within %.2f seconds.", timeout)
                else:
                    logger.info("OledCurtain thread stopped successfully.")

        # Ensure window is destroyed if thread was never started or didn't destroy it
        self._destroy_window()

        if callback is not None:
            try:
                callback(False)
            except Exception as e:
                logger.exception("Error in on_state_change callback during stop: %s", e)

    def poll_once(self, now: Optional[float] = None) -> None:
        """Executes a single cursor check and state evaluation cycle."""
        if now is None:
            now = time.time()

        pos = self.get_cursor_pos()
        if pos is None:
            return

        x, y = pos
        is_inside = self.is_point_in_primary_monitor(x, y)

        should_wake = False
        should_blackout = False

        with self._lock:
            cursor_moved = (self._last_cursor_pos is None) or (
                x != self._last_cursor_pos[0] or y != self._last_cursor_pos[1]
            )
            self._last_cursor_pos = (x, y)

            if is_inside and cursor_moved:
                self._last_activity_time = now
                if self._is_blacked_out:
                    should_wake = True
            else:
                elapsed = now - self._last_activity_time
                if elapsed >= self._timeout_seconds and not self._is_blacked_out:
                    should_blackout = True

        if should_wake:
            self.wake(now=now)
        elif should_blackout:
            self.blackout()

    def _run(self) -> None:
        """Background thread worker loop."""
        logger.debug("OledCurtain background loop starting.")
        try:
            self._init_window()
        except Exception as e:
            logger.error("Error creating curtain window in worker thread: %s", e)
        finally:
            self._ready_event.set()

        while not self._stop_event.is_set():
            try:
                self._pump_messages()
                self.poll_once()
            except Exception as e:
                logger.error("Unexpected error in OledCurtain polling loop: %s", e)

            if self._stop_event.wait(timeout=self.poll_interval):
                break

        try:
            self._destroy_window()
        except Exception as e:
            logger.error("Error destroying curtain window in worker thread: %s", e)

        logger.debug("OledCurtain background loop finished.")

    def _init_window(self) -> None:
        """Creates the Win32 borderless fullscreen blackout window."""
        global _WNDPROC_HOLDER
        user32 = self._user32
        if user32 is None or not hasattr(user32, "CreateWindowExW"):
            return

        try:
            kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
            gdi32 = getattr(getattr(ctypes, "windll", None), "gdi32", None)
            hinst = kernel32.GetModuleHandleW(None) if kernel32 and hasattr(kernel32, "GetModuleHandleW") else None
            hbrush = gdi32.GetStockObject(BLACK_BRUSH) if gdi32 and hasattr(gdi32, "GetStockObject") else None

            class_name = "HdmiSelectorOledCurtainWindow"
            if hasattr(user32, "RegisterClassW") and hasattr(user32, "DefWindowProcW"):
                _WNDPROC_HOLDER = WNDPROC(user32.DefWindowProcW)
                wc = WNDCLASSW()
                wc.style = 0
                wc.lpfnWndProc = _WNDPROC_HOLDER
                wc.hInstance = hinst
                wc.hbrBackground = hbrush
                wc.lpszClassName = class_name
                self._class_atom = user32.RegisterClassW(ctypes.byref(wc))

            left, top, right, bottom = self.get_primary_monitor_rect()
            width = right - left
            height = bottom - top

            ex_style = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            style = WS_POPUP
            hwnd = user32.CreateWindowExW(
                ex_style,
                class_name,
                "HDMI Selector OLED Curtain",
                style,
                left,
                top,
                width,
                height,
                None,
                None,
                hinst,
                None,
            )
            if hwnd:
                with self._lock:
                    self._hwnd = hwnd
                logger.debug("OledCurtain window created: hwnd=%s rect=(%d,%d,%d,%d)", hwnd, left, top, width, height)
        except Exception as e:
            logger.debug("Win32 window creation failed (fallback headless): %s", e)

    def _show_window(self) -> None:
        """Shows the blackout window on the primary monitor asynchronously."""
        if self._hwnd and self._user32:
            try:
                left, top, right, bottom = self.get_primary_monitor_rect()
                width = right - left
                height = bottom - top
                if hasattr(self._user32, "SetWindowPos"):
                    # 0x4000 is SWP_ASYNCWINDOWPOS to avoid cross-thread blocking
                    self._user32.SetWindowPos(
                        self._hwnd,
                        HWND_TOPMOST,
                        left,
                        top,
                        width,
                        height,
                        0x4000 | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                    )
                if hasattr(self._user32, "ShowWindowAsync"):
                    self._user32.ShowWindowAsync(self._hwnd, SW_SHOWNOACTIVATE)
                elif hasattr(self._user32, "ShowWindow"):
                    self._user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            except Exception as e:
                logger.debug("Error showing curtain window: %s", e)

    def _hide_window(self) -> None:
        """Hides the blackout window asynchronously."""
        if self._hwnd and self._user32:
            try:
                if hasattr(self._user32, "ShowWindowAsync"):
                    self._user32.ShowWindowAsync(self._hwnd, SW_HIDE)
                elif hasattr(self._user32, "ShowWindow"):
                    self._user32.ShowWindow(self._hwnd, SW_HIDE)
            except Exception as e:
                logger.debug("Error hiding curtain window: %s", e)

    def _destroy_window(self) -> None:
        """Destroys the blackout window."""
        with self._lock:
            hwnd = self._hwnd
            self._hwnd = None

        if hwnd and self._user32:
            try:
                if hasattr(self._user32, "DestroyWindow"):
                    self._user32.DestroyWindow(hwnd)
            except Exception as e:
                logger.debug("Error destroying curtain window: %s", e)

    def _pump_messages(self) -> None:
        """Dispatches any pending messages for the curtain window."""
        if not self._hwnd or not self._user32 or not hasattr(self._user32, "PeekMessageW"):
            return
        try:
            msg = wintypes.MSG()
            max_messages = 20
            while max_messages > 0:
                max_messages -= 1
                ret = self._user32.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, PM_REMOVE)
                if not ret or getattr(ret, "_mock_name", None) is not None:
                    break
                if hasattr(self._user32, "TranslateMessage"):
                    self._user32.TranslateMessage(ctypes.byref(msg))
                if hasattr(self._user32, "DispatchMessageW"):
                    self._user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            logger.debug("Message pump exception: %s", e)
