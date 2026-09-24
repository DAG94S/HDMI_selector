"""Background HDMI connection monitor service."""

import logging
import threading
from typing import Callable, Optional

from HDMI_selector.core.display_manager import AppMode, DisplayManager

logger = logging.getLogger(__name__)


class HdmiMonitor:
    """Monitors HDMI / external display connectivity in a background daemon thread.

    Provides status change callbacks and automatic fallback recovery when an external
    display is disconnected while in presentation mode to protect the user from a blank screen.
    """

    def __init__(
        self,
        display_manager: DisplayManager,
        poll_interval: float = 3.0,
        on_status_change: Optional[Callable[[bool, list[str]], None]] = None,
        auto_restore: bool = True,
    ) -> None:
        """Initializes HdmiMonitor.

        Args:
            display_manager: DisplayManager instance to query and control displays.
            poll_interval: Interval in seconds between polling checks. Must be positive.
            on_status_change: Optional callback invoked with (is_connected, display_names)
                when HDMI connection status changes.
            auto_restore: If True, automatically restores NORMAL mode when HDMI disconnects
                while in PRESENTATION mode.
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")

        self.display_manager = display_manager
        self.poll_interval = float(poll_interval)
        self.on_status_change = on_status_change
        self.auto_restore = bool(auto_restore)

        self._current_mode: Optional[AppMode] = None
        self._last_status: Optional[bool] = None
        self._last_display_names: list[str] = []

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @property
    def current_mode(self) -> Optional[AppMode]:
        """Current operational mode tracked by the monitor."""
        with self._lock:
            return self._current_mode

    @current_mode.setter
    def current_mode(self, mode: Optional[AppMode | str]) -> None:
        with self._lock:
            if mode is None:
                self._current_mode = None
            elif isinstance(mode, AppMode):
                self._current_mode = mode
            elif isinstance(mode, str):
                self._current_mode = AppMode(mode)
            else:
                raise TypeError(f"Invalid mode type: {type(mode).__name__}")

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

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
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
        self._stop_event.set()
        thread = None
        with self._lock:
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

    def poll_once(self) -> tuple[bool, list[str]]:
        """Checks current display status directly, fires callback if status changed,
        and handles auto-restore if enabled.

        Returns:
            tuple[bool, list[str]]: Current (is_hdmi_connected, active_display_names).
        """
        try:
            technologies = self.display_manager.get_active_display_technologies()
            is_connected = self.display_manager.is_hdmi_connected(technologies)
            display_names = self.display_manager.get_active_display_names(technologies)
        except Exception as e:
            logger.error("Error querying display technologies in HdmiMonitor: %s", e)
            with self._lock:
                return (
                    self._last_status if self._last_status is not None else False,
                    list(self._last_display_names),
                )

        callback_to_call = None
        should_auto_restore = False

        with self._lock:
            previous_status = self._last_status
            previous_names = self._last_display_names
            status_changed = previous_status is not None and (
                previous_status != is_connected or previous_names != display_names
            )

            self._last_status = is_connected
            self._last_display_names = list(display_names)

            if status_changed and self.on_status_change is not None:
                callback_to_call = self.on_status_change

            if (
                self.auto_restore
                and self._current_mode in (AppMode.PRESENTATION, AppMode.TEACHER)
                and not is_connected
            ):
                should_auto_restore = True
                prev_mode = self._current_mode
                self._current_mode = AppMode.NORMAL

        # Invoke callback outside lock to prevent deadlocks
        if callback_to_call is not None:
            try:
                callback_to_call(is_connected, list(display_names))
            except Exception as e:
                logger.error("Error in on_status_change callback: %s", e)

        # Perform auto-restore outside lock
        if should_auto_restore:
            try:
                logger.info(
                    "HDMI disconnected while in %s mode; "
                    "auto-restoring NORMAL mode for safety.",
                    prev_mode.value if isinstance(prev_mode, AppMode) else prev_mode,
                )
                res = self.display_manager.apply_mode(AppMode.NORMAL)
                if isinstance(res, dict) and not res.get("success", False):
                    logger.warning(
                        "Auto-restore apply_mode(NORMAL) was not successful: %s", res
                    )
            except Exception as e:
                logger.error("Error auto-restoring normal mode: %s", e)

        return is_connected, display_names

    def _run(self) -> None:
        """Background daemon polling loop."""
        logger.debug("HdmiMonitor background loop running.")
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as e:
                logger.error("Unexpected error in HdmiMonitor polling loop: %s", e)

            if self._stop_event.wait(timeout=self.poll_interval):
                break
        logger.debug("HdmiMonitor background loop finished.")
