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
    # A single disconnected poll may be a transient glitch: no restore yet
    mock_dm.apply_mode.assert_not_called()

    connected, names = monitor.poll_once()
    assert connected is False
    # Safety restore triggered automatically on 2nd consecutive disconnected poll
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)
    # Mode updated to NORMAL
    assert monitor.current_mode == AppMode.NORMAL

    # 3. Subsequent poll while disconnected does not re-trigger apply_mode
    mock_dm.apply_mode.reset_mock()
    monitor.poll_once()
    mock_dm.apply_mode.assert_not_called()


def test_auto_restore_when_teacher_mode_and_disconnects():
    """Verify that disconnecting HDMI in TEACHER mode automatically restores NORMAL mode."""
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.apply_mode.return_value = {"success": True, "mode": AppMode.NORMAL}

    monitor = HdmiMonitor(display_manager=mock_dm, auto_restore=True)

    # 1. Connected in TEACHER mode
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]
    monitor.poll_once()

    monitor.current_mode = AppMode.TEACHER

    # 2. HDMI disconnects
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    connected, names = monitor.poll_once()

    assert connected is False
    # A single disconnected poll may be a transient glitch: no restore yet
    mock_dm.apply_mode.assert_not_called()

    connected, names = monitor.poll_once()
    assert connected is False
    # Safety restore triggered automatically on 2nd consecutive disconnected poll
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
    monitor.poll_once()
    connected, names = monitor.poll_once()
    assert connected is False
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)


def test_poll_once_query_exception_tolerance():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.is_hdmi_connected.side_effect = RuntimeError("Win32 query failed")

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
    assert mock_dm.is_hdmi_connected.call_count >= 1

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
    mock_dm.is_hdmi_connected.side_effect = RuntimeError("Fatal API crash")

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


def test_stop_called_from_callback():
    mock_dm = MagicMock(spec=DisplayManager)
    monitor_ref = [None]
    stopped_event = threading.Event()

    def on_change(connected, names):
        # Calling stop directly from callback inside the worker thread
        monitor_ref[0].stop()
        stopped_event.set()

    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    monitor = HdmiMonitor(
        display_manager=mock_dm,
        poll_interval=0.02,
        on_status_change=on_change,
    )
    monitor_ref[0] = monitor
    monitor.start()

    try:
        # Trigger status change
        mock_dm.get_active_display_technologies.return_value = [6, 5]
        mock_dm.is_hdmi_connected.return_value = True
        mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]

        assert stopped_event.wait(timeout=1.0)
        # Give a moment for loop to exit since stop_event was set
        time.sleep(0.05)
    finally:
        monitor.stop(timeout=1.0)

    assert monitor.is_running() is False


def test_thread_restart_lifecycle():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    monitor = HdmiMonitor(display_manager=mock_dm, poll_interval=0.02)
    assert monitor.is_running() is False

    # First cycle
    monitor.start()
    assert monitor.is_running() is True
    monitor.stop(timeout=1.0)
    assert monitor.is_running() is False

    # Second cycle (restart)
    monitor.start()
    assert monitor.is_running() is True
    monitor.stop(timeout=1.0)
    assert monitor.is_running() is False


def test_auto_restore_when_apply_mode_returns_failure(caplog):
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.apply_mode.return_value = {"success": False, "error": "CCD failed"}

    monitor = HdmiMonitor(display_manager=mock_dm, auto_restore=True)
    monitor.current_mode = AppMode.PRESENTATION

    mock_dm.get_active_display_technologies.return_value = [6]
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]

    monitor.poll_once()
    connected, names = monitor.poll_once()
    assert connected is False
    assert monitor.current_mode == AppMode.NORMAL
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)


def test_status_change_dispatched_when_display_names_change():
    mock_dm = MagicMock(spec=DisplayManager)
    callbacks = []

    def on_change(connected, names):
        callbacks.append((connected, names))

    mock_dm.get_active_display_technologies.return_value = [6, 5]
    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI 1"]

    monitor = HdmiMonitor(
        display_manager=mock_dm,
        on_status_change=on_change,
    )
    monitor.poll_once()
    assert len(callbacks) == 0

    # Same HDMI boolean (True), but display names changed (e.g. switched port/model)
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI 2"]
    monitor.poll_once()

    assert len(callbacks) == 1
    assert callbacks[0] == (True, ["Internal/Laptop", "HDMI 2"])



# ---------------------------------------------------------------------------
# Reliability: unknown status, consecutive disconnects, grace period, locking
# ---------------------------------------------------------------------------

def _disconnected_dm():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.apply_mode.return_value = {"success": True, "topology_ok": True}
    mock_dm.is_hdmi_connected.return_value = False
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop"]
    return mock_dm


def test_monitor_queries_availability_not_active_paths():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm)
    monitor.poll_once()
    # is_hdmi_connected() without args -> AVAILABLE external targets (QDC_ALL_PATHS)
    mock_dm.is_hdmi_connected.assert_called_once_with()


def test_unknown_status_is_ignored():
    mock_dm = MagicMock(spec=DisplayManager)
    cb = MagicMock()
    monitor = HdmiMonitor(display_manager=mock_dm, on_status_change=cb)

    mock_dm.is_hdmi_connected.return_value = True
    mock_dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]
    monitor.poll_once()
    monitor.current_mode = AppMode.PRESENTATION

    # API error -> None: must not be interpreted as a disconnection
    mock_dm.is_hdmi_connected.return_value = None
    mock_dm.get_active_display_names.return_value = []
    for _ in range(5):
        connected, names = monitor.poll_once()
        assert connected is True
        assert names == ["Internal/Laptop", "HDMI"]

    assert monitor.last_status is True
    cb.assert_not_called()
    mock_dm.apply_mode.assert_not_called()
    assert monitor.current_mode == AppMode.PRESENTATION


def test_unknown_status_without_baseline_returns_false():
    mock_dm = MagicMock(spec=DisplayManager)
    mock_dm.is_hdmi_connected.return_value = None
    mock_dm.get_active_display_names.return_value = []
    monitor = HdmiMonitor(display_manager=mock_dm)
    assert monitor.poll_once() == (False, [])
    assert monitor.last_status is None


def test_single_disconnect_glitch_does_not_restore():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm)
    monitor.current_mode = AppMode.TEACHER

    monitor.poll_once()  # disconnected (1)
    mock_dm.is_hdmi_connected.return_value = True
    monitor.poll_once()  # reconnected -> counter reset
    mock_dm.is_hdmi_connected.return_value = False
    monitor.poll_once()  # disconnected (1 again)

    mock_dm.apply_mode.assert_not_called()
    assert monitor.current_mode == AppMode.TEACHER

    monitor.poll_once()  # disconnected (2) -> restore
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)


def test_on_mode_restored_fired_even_without_status_change():
    mock_dm = _disconnected_dm()
    restored = []
    status_cb = MagicMock()
    monitor = HdmiMonitor(
        display_manager=mock_dm,
        on_status_change=status_cb,
        on_mode_restored=restored.append,
        grace_period=0.0,
    )
    # Status is "disconnected" from the very first poll (no transition at all)
    monitor.current_mode = AppMode.PRESENTATION
    monitor.poll_once()
    monitor.poll_once()

    status_cb.assert_not_called()
    assert restored == [AppMode.NORMAL]
    assert monitor.current_mode == AppMode.NORMAL

    # Fired again on a later independent auto-restore
    monitor.current_mode = AppMode.TEACHER
    monitor.poll_once()
    monitor.poll_once()
    assert restored == [AppMode.NORMAL, AppMode.NORMAL]


def test_on_mode_restored_fired_when_apply_fails_and_exceptions_tolerated():
    mock_dm = _disconnected_dm()
    mock_dm.apply_mode.side_effect = RuntimeError("boom")
    cb = MagicMock(side_effect=RuntimeError("ui gone"))
    monitor = HdmiMonitor(display_manager=mock_dm, on_mode_restored=cb)
    monitor.current_mode = AppMode.TEACHER
    monitor.poll_once()
    monitor.poll_once()
    cb.assert_called_once_with(AppMode.NORMAL)


def test_on_mode_restored_attribute_can_be_assigned_later():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm)
    assert monitor.on_mode_restored is None
    cb = MagicMock()
    monitor.on_mode_restored = cb
    monitor.current_mode = AppMode.PRESENTATION
    monitor.poll_once()
    monitor.poll_once()
    cb.assert_called_once_with(AppMode.NORMAL)


def test_timeout_provider_used_for_auto_restore():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm, timeout_provider=lambda: 300)
    monitor.current_mode = AppMode.PRESENTATION
    monitor.poll_once()
    monitor.poll_once()
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL, timeout_seconds=300)


@pytest.mark.parametrize("provider", [lambda: 0, lambda: "abc", MagicMock(side_effect=RuntimeError("x"))])
def test_invalid_timeout_provider_falls_back_to_default(provider):
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm, timeout_provider=provider)
    monitor.current_mode = AppMode.TEACHER
    monitor.poll_once()
    monitor.poll_once()
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)


def test_notify_mode_change_grace_period_suppresses_restore():
    mock_dm = _disconnected_dm()
    now = [100.0]
    monitor = HdmiMonitor(display_manager=mock_dm, clock=lambda: now[0], grace_period=5.0)

    monitor.notify_mode_change(AppMode.PRESENTATION)
    assert monitor.current_mode == AppMode.PRESENTATION
    assert monitor.in_grace_period() is True

    # Windows reports HDMI missing while switching topology -> ignored during grace
    now[0] = 101.0
    monitor.poll_once()
    now[0] = 103.0
    monitor.poll_once()
    now[0] = 104.9
    monitor.poll_once()
    mock_dm.apply_mode.assert_not_called()

    # Grace expired and still disconnected -> restore
    now[0] = 105.5
    assert monitor.in_grace_period() is False
    monitor.poll_once()
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)
    assert monitor.current_mode == AppMode.NORMAL


def test_notify_mode_change_accepts_strings_and_resets_counter():
    mock_dm = _disconnected_dm()
    now = [0.0]
    monitor = HdmiMonitor(display_manager=mock_dm, clock=lambda: now[0], grace_period=0.0)
    monitor.current_mode = AppMode.EXERCISES
    monitor.poll_once()
    monitor.poll_once()  # counter 2 but EXERCISES does not auto-restore

    monitor.notify_mode_change("teacher")
    assert monitor.current_mode == AppMode.TEACHER
    monitor.poll_once()  # counter restarted -> 1
    mock_dm.apply_mode.assert_not_called()
    monitor.poll_once()
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)

    with pytest.raises(ValueError):
        monitor.notify_mode_change("bogus")


def test_mode_lock_is_public_rlock_and_held_during_restore():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm)
    held = []

    def apply_mode(*args, **kwargs):
        # Another thread must not be able to take the lock while restoring
        result = []
        t = threading.Thread(target=lambda: result.append(monitor.mode_lock.acquire(blocking=False)))
        t.start()
        t.join()
        held.append(not result[0])
        if result[0]:
            monitor.mode_lock.release()
        return {"success": True, "topology_ok": True}

    mock_dm.apply_mode.side_effect = apply_mode
    monitor.current_mode = AppMode.PRESENTATION
    monitor.poll_once()
    monitor.poll_once()

    assert held == [True]
    # Reentrant for the owning thread
    with monitor.mode_lock:
        with monitor.mode_lock:
            pass


def test_restore_postponed_while_ui_holds_mode_lock():
    mock_dm = _disconnected_dm()
    now = [0.0]
    monitor = HdmiMonitor(display_manager=mock_dm, clock=lambda: now[0], grace_period=5.0)
    monitor.current_mode = AppMode.TEACHER

    acquired = threading.Event()
    release = threading.Event()

    def ui_apply():
        with monitor.mode_lock:
            acquired.set()
            release.wait(2.0)

    ui = threading.Thread(target=ui_apply)
    ui.start()
    assert acquired.wait(1.0)
    try:
        monitor.poll_once()
        monitor.poll_once()  # would restore, but UI is applying a mode
        mock_dm.apply_mode.assert_not_called()
        assert monitor.in_grace_period() is True
    finally:
        release.set()
        ui.join(2.0)

    # Grace extended from the moment the lock was found busy
    now[0] = 4.0
    monitor.poll_once()
    monitor.poll_once()
    mock_dm.apply_mode.assert_not_called()

    now[0] = 6.0
    monitor.poll_once()
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)


def test_restore_rechecks_mode_under_lock():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm)
    monitor.current_mode = AppMode.PRESENTATION
    monitor.poll_once()

    # UI switched to EXERCISES between the poll decision and the restore
    original_acquire = monitor.mode_lock.acquire

    class SwitchingLock:
        def acquire(self, blocking=True):
            monitor.current_mode = AppMode.EXERCISES
            return original_acquire(blocking)

        def release(self):
            monitor_lock_release()

    monitor_lock_release = monitor.mode_lock.release
    monitor.mode_lock = SwitchingLock()
    monitor.poll_once()

    mock_dm.apply_mode.assert_not_called()
    assert monitor.current_mode == AppMode.EXERCISES


def test_invalid_disconnect_threshold():
    with pytest.raises(ValueError):
        HdmiMonitor(display_manager=MagicMock(spec=DisplayManager), disconnect_threshold=0)


def test_disconnect_threshold_one_restores_immediately():
    mock_dm = _disconnected_dm()
    monitor = HdmiMonitor(display_manager=mock_dm, disconnect_threshold=1)
    monitor.current_mode = AppMode.PRESENTATION
    monitor.poll_once()
    mock_dm.apply_mode.assert_called_once_with(AppMode.NORMAL)
