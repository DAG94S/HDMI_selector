"""Unit tests for OledCurtain component."""

import ctypes
import threading
import time
from unittest.mock import MagicMock, call, patch
import pytest

from HDMI_selector.core.oled_curtain import (
    OledCurtain,
    get_primary_monitor_rect,
    is_point_in_primary_monitor,
    RECT,
    POINT,
    MONITORINFO,
)


def test_structures_and_types():
    """Verify Win32 ctypes structures and their field layouts."""
    rect = RECT(0, 0, 1920, 1080)
    assert rect.left == 0
    assert rect.top == 0
    assert rect.right == 1920
    assert rect.bottom == 1080

    pt = POINT(100, 200)
    assert pt.x == 100
    assert pt.y == 200

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    mi.rcMonitor = RECT(10, 20, 100, 200)
    assert mi.rcMonitor.left == 10
    assert mi.rcMonitor.bottom == 200


def test_get_primary_monitor_rect_success():
    """Verify get_primary_monitor_rect retrieves rect via MonitorFromPoint and GetMonitorInfoW."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 12345

    def fake_get_monitor_info(hmon, mi_ptr):
        # mi_ptr is byref(mi), so mi_ptr._obj is the struct
        mi_ptr._obj.rcMonitor = RECT(0, 0, 2560, 1440)
        return 1

    mock_user32.GetMonitorInfoW.side_effect = fake_get_monitor_info

    rect = get_primary_monitor_rect(mock_user32)
    assert rect == (0, 0, 2560, 1440)
    mock_user32.MonitorFromPoint.assert_called_once()
    mock_user32.GetMonitorInfoW.assert_called_once()


def test_get_primary_monitor_rect_fallback_system_metrics():
    """Verify fallback to GetSystemMetrics when MonitorFromPoint or GetMonitorInfoW fails."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 0  # Fails
    mock_user32.GetSystemMetrics.side_effect = lambda metric: 3840 if metric == 0 else 2160

    rect = get_primary_monitor_rect(mock_user32)
    assert rect == (0, 0, 3840, 2160)
    assert mock_user32.GetSystemMetrics.call_count >= 2


def test_get_primary_monitor_rect_fallback_default():
    """Verify fallback to default 1920x1080 when user32 is unavailable or raises exception."""
    with patch("ctypes.windll", None, create=True):
        assert get_primary_monitor_rect(None) == (0, 0, 1920, 1080)

    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.side_effect = RuntimeError("DLL failure")
    mock_user32.GetSystemMetrics.side_effect = RuntimeError("DLL failure")

    rect = get_primary_monitor_rect(mock_user32)
    assert rect == (0, 0, 1920, 1080)


def test_is_point_in_primary_monitor_boundary_checks():
    """Verify boundary condition: left <= x < right and top <= y < bottom."""
    rect = (0, 0, 1920, 1080)

    # Top-left inside
    assert is_point_in_primary_monitor(0, 0, rect=rect) is True
    # Bottom-right inside (exclusive bound - 1)
    assert is_point_in_primary_monitor(1919, 1079, rect=rect) is True
    # Center inside
    assert is_point_in_primary_monitor(960, 540, rect=rect) is True

    # Exact boundary (exclusive right and bottom)
    assert is_point_in_primary_monitor(1920, 540, rect=rect) is False
    assert is_point_in_primary_monitor(960, 1080, rect=rect) is False
    assert is_point_in_primary_monitor(1920, 1080, rect=rect) is False

    # Negative coordinates
    assert is_point_in_primary_monitor(-1, 540, rect=rect) is False
    assert is_point_in_primary_monitor(960, -1, rect=rect) is False

    # External projector / secondary monitor coordinate space
    assert is_point_in_primary_monitor(2560, 500, rect=rect) is False
    assert is_point_in_primary_monitor(-1920, 500, rect=rect) is False


def test_curtain_initial_state_and_properties():
    """Verify initial state defaults and property setters with validation."""
    mock_user32 = MagicMock()
    curtain = OledCurtain(user32=mock_user32)

    assert curtain.timeout_seconds == 30
    assert curtain.poll_interval == 0.05
    assert curtain.is_blacked_out() is False
    assert curtain.is_running() is False
    assert curtain.on_state_change is None

    # Dynamic updates
    curtain.timeout_seconds = 15
    assert curtain.timeout_seconds == 15

    curtain.poll_interval = 0.1
    assert curtain.poll_interval == 0.1

    # Validation errors
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        curtain.timeout_seconds = 0

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        curtain.timeout_seconds = -10

    with pytest.raises(ValueError, match="poll_interval must be positive"):
        curtain.poll_interval = 0

    with pytest.raises(ValueError, match="poll_interval must be positive"):
        curtain.poll_interval = -0.5


def test_wake_and_blackout_state_changes_and_callbacks():
    """Verify wake() and blackout() state changes, window calls, and callbacks."""
    mock_user32 = MagicMock()
    state_changes = []

    def on_change(state: bool):
        state_changes.append(state)

    curtain = OledCurtain(on_state_change=on_change, user32=mock_user32)
    # Manually assign mock hwnd to verify window commands
    curtain._hwnd = 99999

    assert curtain.is_blacked_out() is False

    # 1. Trigger blackout
    curtain.blackout()
    assert curtain.is_blacked_out() is True
    assert state_changes == [True]
    mock_user32.ShowWindow.assert_called_with(99999, 4)  # SW_SHOWNOACTIVATE

    # Redundant blackout should not fire duplicate callback
    curtain.blackout()
    assert state_changes == [True]

    # 2. Trigger wake
    curtain.wake()
    assert curtain.is_blacked_out() is False
    assert state_changes == [True, False]
    mock_user32.ShowWindow.assert_called_with(99999, 0)  # SW_HIDE

    # Redundant wake should not fire duplicate callback
    curtain.wake()
    assert state_changes == [True, False]


def test_callback_exception_handling():
    """Verify that an exception raised by on_state_change does not crash wake or blackout."""
    failing_cb = MagicMock(side_effect=RuntimeError("UI error"))
    curtain = OledCurtain(on_state_change=failing_cb)

    # Should not raise exception
    curtain.blackout()
    assert curtain.is_blacked_out() is True

    curtain.wake()
    assert curtain.is_blacked_out() is False


def test_cursor_movement_inside_monitor_wakes_and_resets_timer():
    """Verify cursor movement inside primary monitor wakes curtain and resets activity timer."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 1
    mock_user32.GetMonitorInfoW.side_effect = lambda hmon, mi: setattr(
        mi._obj, "rcMonitor", RECT(0, 0, 1920, 1080)
    ) or 1

    curtain = OledCurtain(timeout_seconds=30, user32=mock_user32)
    curtain.blackout()
    assert curtain.is_blacked_out() is True

    t0 = 1000.0
    curtain._last_activity_time = t0
    curtain._last_cursor_pos = (100, 100)

    # Move cursor inside primary monitor at t = 1010.0
    t1 = 1010.0
    with patch.object(curtain, "get_cursor_pos", return_value=(150, 100)):
        curtain.poll_once(now=t1)

    assert curtain.is_blacked_out() is False
    assert curtain.last_activity_time == t1


def test_cursor_movement_outside_monitor_does_not_wake_or_reset_timer():
    """Verify cursor movement outside monitor 1 (on secondary/projector) does NOT wake curtain or reset timer."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 1
    mock_user32.GetMonitorInfoW.side_effect = lambda hmon, mi: setattr(
        mi._obj, "rcMonitor", RECT(0, 0, 1920, 1080)
    ) or 1

    curtain = OledCurtain(timeout_seconds=30, user32=mock_user32)
    curtain.blackout()
    assert curtain.is_blacked_out() is True

    t0 = 1000.0
    curtain._last_activity_time = t0
    curtain._last_cursor_pos = (2000, 500)  # On projector

    # Move cursor on projector to (2100, 500) at t = 1010.0
    t1 = 1010.0
    with patch.object(curtain, "get_cursor_pos", return_value=(2100, 500)):
        curtain.poll_once(now=t1)

    # Must remain blacked out, and activity timer must NOT reset
    assert curtain.is_blacked_out() is True
    assert curtain.last_activity_time == t0


def test_inactivity_timeout_triggers_blackout():
    """Verify that when now - last_activity >= timeout_seconds and awake, triggers blackout."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 1
    mock_user32.GetMonitorInfoW.side_effect = lambda hmon, mi: setattr(
        mi._obj, "rcMonitor", RECT(0, 0, 1920, 1080)
    ) or 1

    curtain = OledCurtain(timeout_seconds=30, user32=mock_user32)
    assert curtain.is_blacked_out() is False

    t0 = 1000.0
    curtain._last_activity_time = t0
    curtain._last_cursor_pos = (500, 500)

    # 1. At 29 seconds (cursor not moved), still awake
    with patch.object(curtain, "get_cursor_pos", return_value=(500, 500)):
        curtain.poll_once(now=t0 + 29.0)
    assert curtain.is_blacked_out() is False

    # 2. At 30 seconds (cursor not moved), triggers blackout
    with patch.object(curtain, "get_cursor_pos", return_value=(500, 500)):
        curtain.poll_once(now=t0 + 30.0)
    assert curtain.is_blacked_out() is True


def test_inactivity_while_moving_on_projector_triggers_blackout():
    """Verify that moving cursor on projector does not prevent inactivity blackout on primary."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 1
    mock_user32.GetMonitorInfoW.side_effect = lambda hmon, mi: setattr(
        mi._obj, "rcMonitor", RECT(0, 0, 1920, 1080)
    ) or 1

    curtain = OledCurtain(timeout_seconds=30, user32=mock_user32)
    assert curtain.is_blacked_out() is False

    t0 = 1000.0
    curtain._last_activity_time = t0
    curtain._last_cursor_pos = (2000, 500)

    # User moves mouse around on projector at t = 1035.0 (> 30s after t0)
    with patch.object(curtain, "get_cursor_pos", return_value=(2200, 600)):
        curtain.poll_once(now=t0 + 35.0)

    assert curtain.is_blacked_out() is True


def test_dynamic_timeout_reduction():
    """Verify reducing timeout triggers blackout if elapsed time exceeds new timeout."""
    mock_user32 = MagicMock()
    curtain = OledCurtain(timeout_seconds=30, user32=mock_user32)
    t0 = 1000.0
    curtain._last_activity_time = t0
    curtain._last_cursor_pos = (100, 100)

    # 15s elapsed, timeout is 30s -> awake
    with patch.object(curtain, "get_cursor_pos", return_value=(100, 100)):
        curtain.poll_once(now=t0 + 15.0)
    assert curtain.is_blacked_out() is False

    # Reduce timeout to 10s
    curtain.timeout_seconds = 10

    # Next poll at same time (15s elapsed > 10s) -> blackout!
    with patch.object(curtain, "get_cursor_pos", return_value=(100, 100)):
        curtain.poll_once(now=t0 + 15.0)
    assert curtain.is_blacked_out() is True


def test_get_cursor_pos_ctypes():
    """Verify get_cursor_pos reads POINT struct from user32.GetCursorPos."""
    mock_user32 = MagicMock()

    def fake_get_cursor(pt_ptr):
        pt_ptr._obj.x = 450
        pt_ptr._obj.y = 800
        return 1

    mock_user32.GetCursorPos.side_effect = fake_get_cursor

    curtain = OledCurtain(user32=mock_user32)
    pos = curtain.get_cursor_pos()
    assert pos == (450, 800)


def test_get_cursor_pos_failure_returns_none():
    """Verify get_cursor_pos returns None if GetCursorPos fails or raises."""
    mock_user32 = MagicMock()
    mock_user32.GetCursorPos.return_value = 0  # Failed

    curtain = OledCurtain(user32=mock_user32)
    assert curtain.get_cursor_pos() is None

    mock_user32.GetCursorPos.side_effect = RuntimeError("Failed")
    assert curtain.get_cursor_pos() is None


def test_start_and_stop_lifecycle():
    """Verify thread start, stop, and idempotency."""
    mock_user32 = MagicMock()
    curtain = OledCurtain(poll_interval=0.01, user32=mock_user32)

    assert curtain.is_running() is False

    # Start
    curtain.start()
    assert curtain.is_running() is True

    # Redundant start is a no-op
    curtain.start()
    assert curtain.is_running() is True

    # Allow thread to execute several iterations
    time.sleep(0.05)

    # Stop
    curtain.stop(timeout=1.0)
    assert curtain.is_running() is False

    # Redundant stop is a no-op
    curtain.stop(timeout=1.0)
    assert curtain.is_running() is False


def test_window_operations_robust_without_user32():
    """Verify window operations handle absence of Win32 gracefully."""
    with patch("ctypes.windll", None, create=True):
        curtain = OledCurtain(user32=None)
        # Should not raise even without Win32/user32
        curtain.start()
        curtain.blackout()
        curtain.wake()
        curtain.stop()
        assert curtain.is_running() is False


def test_curtain_is_point_in_primary_monitor_method():
    """Verify curtain instance method delegates to monitor rect."""
    mock_user32 = MagicMock()
    mock_user32.MonitorFromPoint.return_value = 1
    mock_user32.GetMonitorInfoW.side_effect = lambda hmon, mi: setattr(
        mi._obj, "rcMonitor", RECT(0, 0, 1920, 1080)
    ) or 1

    curtain = OledCurtain(user32=mock_user32)
    assert curtain.is_point_in_primary_monitor(500, 500) is True
    assert curtain.is_point_in_primary_monitor(1920, 500) is False
    assert curtain.is_point_in_primary_monitor(-1, 500) is False


def test_concurrent_thread_safety():
    """Verify thread-safety when multiple threads concurrently invoke wake, blackout, and poll_once."""
    mock_user32 = MagicMock()
    curtain = OledCurtain(user32=mock_user32)
    errors = []

    def worker():
        try:
            for i in range(50):
                curtain.blackout()
                curtain.wake()
                curtain.poll_once()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert errors == []


def test_stop_called_from_worker_thread_does_not_deadlock():
    """Verify calling stop() from within the polling thread itself does not deadlock on join()."""
    mock_user32 = MagicMock()
    curtain = OledCurtain(user32=mock_user32)
    curtain.start()

    # Simulate stopping from worker thread
    with patch("threading.current_thread", return_value=curtain._thread):
        curtain.stop(timeout=1.0)

    assert curtain._thread is None


def test_real_windows_host_smoke_test():
    """Smoke test on actual Windows host with real user32."""
    if not hasattr(ctypes, "windll"):
        pytest.skip("Not running on Windows with windll")

    curtain = OledCurtain(timeout_seconds=5)
    rect = curtain.get_primary_monitor_rect()
    assert isinstance(rect, tuple)
    assert len(rect) == 4
    left, top, right, bottom = rect
    assert right > left
    assert bottom > top

    # Full real lifecycle
    curtain.start()
    assert curtain.is_running() is True
    curtain.blackout()
    assert curtain.is_blacked_out() is True
    curtain.wake()
    assert curtain.is_blacked_out() is False
    curtain.stop(timeout=1.0)
    assert curtain.is_running() is False
