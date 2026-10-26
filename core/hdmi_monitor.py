"""Background HDMI connection monitor service."""

import logging
import threading
import time
from typing import Callable, Optional

from HDMI_selector.core.display_manager import AppMode, DisplayManager

logger = logging.getLogger(__name__)

# Seconds after a mode change during which auto-restore is suppressed (Windows
# transiently reports the external display as missing while switching topology).
DEFAULT_GRACE_PERIOD = 5.0
# Number of consecutive "disconnected" polls required before auto-restoring.
DEFAULT_DISCONNECT_THRESHOLD = 2

AUTO_RESTORE_MODES = (AppMode.PRESENTATION, AppMode.TEACHER)


class HdmiMonitor:
    """Monitors HDMI / external display connectivity in a background daemon thread.

    Provides status change callbacks and automatic fallback recovery when an external
    display is disconnected while in presentation or teacher mode to protect the user from a blank screen.

    Thread-safety contract with the UI:
        * ``mode_lock`` (public RLock) is held by the monitor while it auto-restores NORMAL
          mode, and should be held by the UI while it applies a mode, so both never cross.
        * ``notify_mode_change(mode)`` must be called when the UI starts applying a mode; it
          opens a grace period in which auto-restore is suppressed.
        * An "unknown" status (``is_hdmi_connected()`` returning None) is ignored.
    """

    def __init__(
        self,
        display_manager: DisplayManager,
        poll_interval: float = 3.0,
        on_status_change: Optional[Callable[[bool, list[str]], None]] = None,
        auto_restore: bool = True,
        on_mode_restored: Optional[Callable[[AppMode], None]] = None,
        timeout_provider: Optional[Callable[[], int]] = None,
        grace_period: float = DEFAULT_GRACE_PERIOD,
        disconnect_threshold: int = DEFAULT_DISCONNECT_THRESHOLD,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        """Initializes HdmiMonitor.

        Args:
            display_manager: DisplayManager instance to query and control displays.
            poll_interval: Interval in seconds between polling checks. Must be positive.
            on_status_change: Optional callback invoked with (is_connected, display_names)
                when HDMI connection status changes.
            auto_restore: If True, automatically restores NORMAL mode when HDMI disconnects
                while in PRESENTATION or TEACHER mode.
            on_mode_restored: Optional callback invoked (from the monitor thread) with
                AppMode.NORMAL every time the monitor performs an auto-restore.
            timeout_provider: Optional callable returning the screensaver timeout (seconds)
                to use when auto-restoring NORMAL mode.
            grace_period: Seconds after notify_mode_change() during which auto-restore
                is suppressed.
            disconnect_threshold: Consecutive "disconnected" polls required to auto-restore.
            clock: Optional monotonic clock function (injectable for tests).
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if disconnect_threshold < 1:
            raise ValueError("disconnect_threshold must be >= 1")

        self.display_manager = display_manager
        self.poll_interval = float(poll_interval)
        self.on_status_change = on_status_change
        self.auto_restore = bool(auto_restore)
        self.on_mode_restored = on_mode_restored
        self.timeout_provider = timeout_provider
        self.grace_period = max(0.0, float(grace_period))
        self.disconnect_threshold = int(disconnect_threshold)
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic

        self._current_mode: Optional[AppMode] = None
        self._last_status: Optional[bool] = None
        self._last_display_names: list[str] = []
        self._consecutive_disconnects = 0
        self._grace_until: float = 0.0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        # Public lock serializing mode application between the UI and auto-restore.
        self.mode_lock = threading.RLock()

    @staticmethod
    def _coerce_mode(mode: Optional[AppMode | str]) -> Optional[AppMode]:
        """Converts a mode value (AppMode, str or None) to Optional[AppMode]."""
        if mode is None:
            return None
        if isinstance(mode, AppMode):
            return mode
        if isinstance(mode, str):
            return AppMode(mode)
        raise TypeError(f"Invalid mode type: {type(mode).__name__}")

    @property
    def current_mode(self) -> Optional[AppMode]:
        """Current operational mode tracked by the monitor."""
        with self._lock:
            return self._current_mode

    @current_mode.setter
    def current_mode(self, mode: Optional[AppMode | str]) -> None:
        coerced = self._coerce_mode(mode)
        with self._lock:
            self._current_mode = coerced

    @property
    def last_status(self) -> Optional[bool]:
        """Last known HDMI connection status."""
        with self._lock:
            return self._last_status

    @last_status.setter
    def last_status(self, value: Optional[bool]) -> None:
        with self._lock:
            self._last_status = value

    @property
    def last_display_names(self) -> list[str]:
        """Last known active display names."""
        with self._lock:
            return list(self._last_display_names)

    @last_display_names.setter
    def last_display_names(self, value: list[str]) -> None:
        with self._lock:
            self._last_display_names = list(value)

    def in_grace_period(self) -> bool:
        """Returns True while auto-restore is suppressed after a mode change."""
        with self._lock:
            return self._clock() < self._grace_until

    def notify_mode_change(self, mode: Optional[AppMode | str]) -> None:
        """Records a mode change started by the UI and opens the grace period.

        Sets current_mode, resets the consecutive-disconnect counter and suppresses
        auto-restore for ``grace_period`` seconds, because Windows transiently reports
        the external display as missing while the topology is being switched.
        """
        coerced = self._coerce_mode(mode)
        with self._lock:
            self._current_mode = coerced
            self._consecutive_disconnects = 0
            self._grace_until = self._clock() + self.grace_period

    def is_running(self) -> bool:
        """Returns True if the background polling thread is active."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Starts the daemon polling thread in the background."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("HdmiMonitor thread is already running.")
                return

            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                args=(self._stop_event,),
                name="HdmiMonitorThread",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "HdmiMonitor started with poll_interval=%.2fs (auto_restore=%s)",
                self.poll_interval,
                self.auto_restore,
            )

    def stop(self, timeout: float = 2.0) -> None:
        """Stops the background polling thread.

        Args:
            timeout: Maximum seconds to wait for thread termination.
        """
        with self._lock:
            self._stop_event.set()
            thread = self._thread

        if thread is not None and thread.is_alive():
            if thread is not threading.current_thread():
                thread.join(timeout=timeout)
                if thread.is_alive():
                    logger.warning(
                        "HdmiMonitor thread did not stop within %.2f seconds.", timeout
                    )
                else:
                    logger.info("HdmiMonitor thread stopped successfully.")
            else:
                logger.info("HdmiMonitor stop called from worker thread; stop event set.")

    def _query_status(self) -> tuple[Optional[bool], list[str]]:
        """Queries (is_connected, active_display_names) from the DisplayManager.

        is_connected reflects AVAILABLE external displays (even if inactive) and may be
        None when the state is unknown.
        """
        is_connected = self.display_manager.is_hdmi_connected()
        display_names = self.display_manager.get_active_display_names()
        if is_connected is not None:
            is_connected = bool(is_connected)
        return is_connected, list(display_names or [])

    def poll_once(self) -> tuple[bool, list[str]]:
        """Checks current display status directly, fires callback if status changed,
        and handles auto-restore if enabled.

        Unknown status (API error) is ignored and the last known state is returned.
        Auto-restore requires ``disconnect_threshold`` consecutive disconnected polls,
        is suppressed during the grace period and while a mode change holds mode_lock.

        Returns:
            tuple[bool, list[str]]: Current (is_hdmi_connected, active_display_names).
        """
        try:
            is_connected, display_names = self._query_status()
        except Exception as e:
            logger.error("Error querying display technologies in HdmiMonitor: %s", e)
            is_connected, display_names = None, []

        if is_connected is None:
            logger.debug("HDMI status unknown in this poll; ignoring.")
            with self._lock:
                return (
                    self._last_status if self._last_status is not None else False,
                    list(self._last_display_names),
                )

        callback_to_call = None
        restore_candidate = False

        with self._lock:
            previous_status = self._last_status
            previous_names = self._last_display_names
            status_changed = previous_status is not None and (
                previous_status != is_connected or previous_names != display_names
            )

            self._last_status = is_connected
            self._last_display_names = list(display_names)

            if is_connected:
                self._consecutive_disconnects = 0
            else:
                self._consecutive_disconnects += 1

            if status_changed and self.on_status_change is not None:
                callback_to_call = self.on_status_change

            if (
                self.auto_restore
                and not is_connected
                and self._current_mode in AUTO_RESTORE_MODES
                and self._consecutive_disconnects >= self.disconnect_threshold
                and self._clock() >= self._grace_until
            ):
                restore_candidate = True

        # Invoke callback outside lock to prevent deadlocks
        if callback_to_call is not None:
            try:
                callback_to_call(is_connected, list(display_names))
            except Exception as e:
                logger.error("Error in on_status_change callback: %s", e)

        if restore_candidate:
            self._try_auto_restore()

        return is_connected, display_names

    def _try_auto_restore(self) -> bool:
        """Restores NORMAL mode under mode_lock unless a UI mode change is in progress.

        Returns:
            True if the auto-restore was performed.
        """
        if not self.mode_lock.acquire(blocking=False):
            # The UI is applying a mode right now: extend the grace period instead.
            logger.debug("Mode change in progress; postponing auto-restore.")
            with self._lock:
                self._consecutive_disconnects = 0
                self._grace_until = max(self._grace_until, self._clock() + self.grace_period)
            return False

        try:
            with self._lock:
                # Re-check under the lock: the UI may have changed mode meanwhile.
                if (
                    not self.auto_restore
                    or self._current_mode not in AUTO_RESTORE_MODES
                    or self._last_status is not False
                    or self._clock() < self._grace_until
                ):
                    return False
                prev_mode = self._current_mode
                self._current_mode = AppMode.NORMAL
                self._consecutive_disconnects = 0
                self._grace_until = self._clock() + self.grace_period

            logger.info(
                "HDMI disconnected while in %s mode; auto-restoring NORMAL mode for safety.",
                prev_mode.value if isinstance(prev_mode, AppMode) else prev_mode,
            )
            try:
                timeout = self._get_restore_timeout()
                if timeout is not None:
                    res = self.display_manager.apply_mode(AppMode.NORMAL, timeout_seconds=timeout)
                else:
                    res = self.display_manager.apply_mode(AppMode.NORMAL)
                if isinstance(res, dict) and not res.get("topology_ok", res.get("success", False)):
                    logger.warning(
                        "Auto-restore apply_mode(NORMAL) was not successful: %s", res
                    )
            except Exception as e:
                logger.error("Error auto-restoring normal mode: %s", e)
        finally:
            self.mode_lock.release()

        callback = self.on_mode_restored
        if callback is not None:
            try:
                callback(AppMode.NORMAL)
            except Exception as e:
                logger.error("Error in on_mode_restored callback: %s", e)
        return True

    def _get_restore_timeout(self) -> Optional[int]:
        """Returns the screensaver timeout from timeout_provider, or None if unavailable."""
        provider = self.timeout_provider
        if provider is None:
            return None
        try:
            value = int(provider())
        except Exception as e:
            logger.warning("timeout_provider failed (%s); using default timeout", e)
            return None
        if value <= 0:
            logger.warning("timeout_provider returned invalid value %r; using default", value)
            return None
        return value

    def _run(self, stop_event: Optional[threading.Event] = None) -> None:
        """Background daemon polling loop."""
        if stop_event is None:
            stop_event = self._stop_event
        logger.debug("HdmiMonitor background loop running.")
        while not stop_event.is_set():
            try:
                self.poll_once()
            except Exception as e:
                logger.error("Unexpected error in HdmiMonitor polling loop: %s", e)

            if stop_event.wait(timeout=self.poll_interval):
                break
        logger.debug("HdmiMonitor background loop finished.")
