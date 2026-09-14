import threading
import time
from unittest.mock import MagicMock, call
import pytest

from HDMI_selector.core.display_manager import AppMode, DisplayManager
from HDMI_selector.core.hdmi_monitor import HdmiMonitor


def test_init_defaults():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor = HdmiMonitor(display_manager=mock_dm)

    assert monitor.display_manager is mock_dm
    assert monitor.poll_interval == 3.0
    assert monitor.on_status_change is None
    assert monitor.auto_restore is True
    assert monitor.current_mode is None
    assert monitor.last_status is None
    assert monitor.last_display_names == []
    assert monitor.is_running() is False


def test_init_custom_params():
    mock_dm = MagicMock(spec=DisplayManager)
    callback = MagicMock()
    monitor = HdmiMonitor(
        display_manager=mock_dm,
        poll_interval=1.5,
        on_status_change=callback,
        auto_restore=False,
    )

    assert monitor.poll_interval == 1.5
    assert monitor.on_status_change is callback
    assert monitor.auto_restore is False


def test_init_invalid_poll_interval():
    mock_dm = MagicMock(spec=DisplayManager)
    with pytest.raises(ValueError, match="poll_interval must be positive"):
        HdmiMonitor(display_manager=mock_dm, poll_interval=0)

    with pytest.raises(ValueError, match="poll_interval must be positive"):
        HdmiMonitor(display_manager=mock_dm, poll_interval=-1.0)


def test_current_mode_property():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor = HdmiMonitor(display_manager=mock_dm)

    assert monitor.current_mode is None

    monitor.current_mode = AppMode.PRESENTATION
    assert monitor.current_mode == AppMode.PRESENTATION

    # String conversion
    monitor.current_mode = "exercises"
    assert monitor.current_mode == AppMode.EXERCISES

    monitor.current_mode = "normal"
    assert monitor.current_mode == AppMode.NORMAL

    monitor.current_mode = None
    assert monitor.current_mode is None

    with pytest.raises(ValueError):
        monitor.current_mode = "invalid_mode"

    with pytest.raises(TypeError):
        monitor.current_mode = 12345


def test_last_status_and_display_names_properties():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor = HdmiMonitor(display_manager=mock_dm)

    assert monitor.last_status is None
    assert monitor.last_display_names == []

    monitor.last_status = True
    assert monitor.last_status is True

    names = ["HDMI", "Internal/Laptop"]
    monitor.last_display_names = names
    assert monitor.last_display_names == names

    # Modifying original list should not mutate monitor's internal list
    names.append("Extra")
    assert monitor.last_display_names == ["HDMI", "Internal/Laptop"]


def test_poll_once_initial_baseline():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    cb = MagicMock()
    monitor = HdmiMonitor(display_manager=mock_dm, on_status_change=cb)

    connected, names = monitor.poll_once()

    assert connected is False
    assert names == ["Internal/Laptop"]
    assert monitor.last_status is False
    assert monitor.last_display_names == ["Internal/Laptop"]
    # Initial status establishment does not trigger on_status_change
    cb.assert_not_called()


def test_status_transition_detection_and_callback():
    mock_dm = MagicMock(spec=DisplayManager)
    cb = MagicMock()
    monitor = HdmiMonitor(display_manager=mock_dm, on_status_change=cb)

    # 1. Baseline: disconnected
    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    connected, names = monitor.poll_once()
    assert connected is False
    assert cb.call_count == 0

    # 2. Transition: disconnected -> connected
    mock_dm.get_active_display_technologies.return_value = [6, 5]
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]

    connected, names = monitor.poll_once()
    assert connected is True
    assert names == ["Internal/Laptop", "HDMI"]
    assert monitor.last_status is True
    assert cb.call_count == 1
    cb.assert_called_with(True, ["Internal/Laptop", "HDMI"])

    # 3. Same state: no extra callback
    connected, names = monitor.poll_once()
    assert connected is True
    assert cb.call_count == 1

    # 4. Transition: connected -> disconnected
    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    connected, names = monitor.poll_once()
    assert connected is False
    assert names == ["Internal/Laptop"]
    assert monitor.last_status is False
    assert cb.call_count == 2
    cb.assert_called_with(False, ["Internal/Laptop"])


def test_callback_exception_tolerance():
    mock_dm = MagicMock(spec=DisplayManager)
    cb = MagicMock(side_effect=RuntimeError("Callback exploded"))
    monitor = HdmiMonitor(display_manager=mock_dm, on_status_change=cb)

    # Baseline disconnected
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]
    monitor.poll_once()

    # Transition to connected; callback raises exception
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["HDMI"]

    connected, names = monitor.poll_once()
    assert connected is True
    assert monitor.last_status is True
    cb.assert_called_once()


def test_auto_restore_when_presentation_mode_and_disconnects():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.apply_mode.return_value = {"success": True, "mode": AppMode.NORMAL}

    monitor = HdmiMonitor(display_manager=mock_dm, auto_restore=True)

    # 1. Connected in PRESENTATION mode
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["HDMI"]
    monitor.poll_once()

    monitor.current_mode = AppMode.PRESENTATION

    # 2. HDMI physically disconnects
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    connected, names = monitor.poll_once()

    assert connected is False
    # Safety restore triggered automatically
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)
    # Mode updated to NORMAL
    assert monitor.current_mode == AppMode.NORMAL

    # 3. Subsequent poll while disconnected does not re-trigger apply_mode
    mock_dm.apply_mode.reset_mock()
    monitor.poll_once()
    mock_dm.apply_mode.assert_not_called()


def test_auto_restore_disabled():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor = HdmiMonitor(display_manager=mock_dm, auto_restore=False)

    # Connected
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["HDMI"]
    monitor.poll_once()

    monitor.current_mode = AppMode.PRESENTATION

    # Disconnects
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]
    monitor.poll_once()

    mock_dm.apply_mode.assert_not_called()
    assert monitor.current_mode == AppMode.PRESENTATION


def test_auto_restore_not_triggered_for_exercises_or_normal_mode():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor = HdmiMonitor(display_manager=mock_dm, auto_restore=True)

    # Connected
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["HDMI"]
    monitor.poll_once()

    # Mode is EXERCISES
    monitor.current_mode = AppMode.EXERCISES

    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]
    monitor.poll_once()

    mock_dm.apply_mode.assert_not_called()
    assert monitor.current_mode == AppMode.EXERCISES

    # Mode is NORMAL
    monitor.current_mode = AppMode.NORMAL
    monitor.poll_once()
    mock_dm.apply_mode.assert_not_called()


def test_auto_restore_exception_tolerance():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.apply_mode.side_effect = RuntimeError("apply_mode failed")

    monitor = HdmiMonitor(display_manager=mock_dm, auto_restore=True)
    monitor.current_mode = AppMode.PRESENTATION

    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    # Should not raise exception
    connected, names = monitor.poll_once()
    assert connected is False
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)


def test_poll_once_query_exception_tolerance():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.get_active_display_technologies.side_effect = RuntimeError("Win32 query failed")

    monitor = HdmiMonitor(display_manager=mock_dm)
    monitor.last_status = True
    monitor.last_display_names = ["HDMI"]

    # Should safely return last known state
    connected, names = monitor.poll_once()
    assert connected is True
    assert names == ["HDMI"]


def test_monitor_lifecycle_start_stop_is_running():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    monitor = HdmiMonitor(display_manager=mock_dm, poll_interval=0.05)

    assert monitor.is_running() is False

    monitor.start()
    assert monitor.is_running() is True

    # Duplicate start is a safe no-op
    monitor.start()
    assert monitor.is_running() is True

    # Wait briefly for thread to execute at least one poll
    time.sleep(0.1)
    assert mock_dm.get_active_display_technologies.call_count >= 1

    monitor.stop(timeout=1.0)
    assert monitor.is_running() is False

    # Redundant stop is safe
    monitor.stop(timeout=1.0)
    assert monitor.is_running() is False


def test_stop_before_start():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor = HdmiMonitor(display_manager=mock_dm)
    # Should safely no-op
    monitor.stop(timeout=0.5)
    assert monitor.is_running() is False


def test_background_thread_status_transition_dispatch():
    mock_dm = MagicMock(spec=DisplayManager)
    event = threading.Event()
    dispatched_statuses = []

    def on_change(connected, names):
        dispatched_statuses.append((connected, names))
        event.set()

    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    monitor = HdmiMonitor(
        display_manager=mock_dm,
        poll_interval=0.02,
        on_status_change=on_change,
    )
    monitor.start()

    try:
        # Give initial poll time to run
        time.sleep(0.05)
        assert len(dispatched_statuses) == 0

        # Change mock to connected
        mock_dm.get_active_display_technologies.return_value = [6, 5]
        mock_dm.is_hdmi_connected.return_value = True
        mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]

        # Wait for callback in thread
        assert event.wait(timeout=1.0)
        assert len(dispatched_statuses) >= 1
        assert dispatched_statuses[0] == (True, ["Internal/Laptop", "HDMI"])
    finally:
        monitor.stop(timeout=1.0)


def test_polling_thread_query_exception_tolerance():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.get_active_display_technologies.side_effect = RuntimeError("Fatal API crash")

    monitor = HdmiMonitor(display_manager=mock_dm, poll_interval=0.02)
    monitor.start()

    try:
        # Let it spin through multiple exception iterations
        time.sleep(0.1)
        # Thread should still be running and not crashed
        assert monitor.is_running() is True
    finally:
        monitor.stop(timeout=1.0)

    assert monitor.is_running() is False


def test_core_package_exports_hdmi_monitor():
    from HDMI_selector.core import HdmiMonitor as ExportedMonitor
    import HDMI_selector.core as core_pkg

    assert ExportedMonitor is HdmiMonitor
    assert "HdmiMonitor" in core_pkg.__all__
