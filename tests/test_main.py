"""Unit tests for the CLI launcher and main entry point."""

import json
from unittest.mock import MagicMock, patch
import pytest

from HDMI_selector.core.config import AppConfig
from HDMI_selector.core.display_manager import AppMode, DisplayManager
from HDMI_selector.main import main


@pytest.fixture
def mock_display_manager():
    """Mock DisplayManager for CLI tests."""
    with patch("HDMI_selector.main.DisplayManager") as mock_dm_cls:
        dm_inst = MagicMock(spec=DisplayManager)
        mock_dm_cls.return_value = dm_inst

        dm_inst.get_active_display_technologies.return_value = [6, 5]
        dm_inst.is_hdmi_connected.return_value = True
        dm_inst.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]
        dm_inst.get_screensaver_state.return_value = {"active": True, "timeout": 60}
        dm_inst.apply_mode.return_value = {
            "success": True,
            "mode": AppMode.NORMAL,
            "topology": "internal",
            "screensaver": True,
            "timeout": 60,
        }
        yield dm_inst


@pytest.fixture
def mock_app_config():
    """Mock AppConfig for CLI tests."""
    with patch("HDMI_selector.main.AppConfig") as mock_cfg_cls:
        cfg_inst = AppConfig(
            screensaver_timeout=60,
            default_mode="normal",
            theme="dark",
            poll_interval_seconds=3,
            auto_restore_on_disconnect=True,
        )
        mock_cfg_cls.return_value = cfg_inst
        yield cfg_inst


@pytest.fixture
def mock_hdmi_app():
    """Mock HdmiSelectorApp to prevent GUI from opening."""
    with patch("HDMI_selector.main.HdmiSelectorApp") as mock_app_cls:
        app_inst = MagicMock()
        mock_app_cls.return_value = app_inst
        yield mock_app_cls, app_inst


def test_status_command_outputs_valid_json(mock_display_manager, mock_app_config, capsys):
    """Test that --status outputs valid JSON with expected fields and returns 0."""
    ret = main(["--status"])
    assert ret == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)

    assert "is_hdmi_connected" in data
    assert "active_displays" in data
    assert "screensaver" in data
    assert "config" in data

    assert data["is_hdmi_connected"] is True
    assert data["active_displays"] == ["Internal/Laptop", "HDMI"]
    assert data["screensaver"] == {"active": True, "timeout": 60}
    assert data["config"]["screensaver_timeout"] == 60
    assert data["config"]["theme"] == "dark"


def test_mode_presentation(mock_display_manager, capsys):
    """Test that --mode presentation invokes apply_mode(AppMode.PRESENTATION) and returns 0."""
    mock_display_manager.apply_mode.return_value = {
        "success": True,
        "mode": AppMode.PRESENTATION,
        "topology": "external",
        "screensaver": False,
        "timeout": None,
    }

    ret = main(["--mode", "presentation"])
    assert ret == 0

    mock_display_manager.apply_mode.assert_called_once_with(AppMode.PRESENTATION)
    captured = capsys.readouterr()
    assert "presentation" in captured.out.lower()
    assert captured.err == ""


def test_mode_exercises(mock_display_manager, capsys):
    """Test that --mode exercises invokes apply_mode(AppMode.EXERCISES) and returns 0."""
    mock_display_manager.apply_mode.return_value = {
        "success": True,
        "mode": AppMode.EXERCISES,
        "topology": "extend",
        "screensaver": False,
        "timeout": None,
    }

    ret = main(["--mode", "exercises"])
    assert ret == 0

    mock_display_manager.apply_mode.assert_called_once_with(AppMode.EXERCISES)
    captured = capsys.readouterr()
    assert "exercises" in captured.out.lower()
    assert captured.err == ""


def test_mode_normal_with_timeout(mock_display_manager, capsys):
    """Test that --mode normal --timeout 120 calls apply_mode(AppMode.NORMAL, timeout_seconds=120) and returns 0."""
    mock_display_manager.apply_mode.return_value = {
        "success": True,
        "mode": AppMode.NORMAL,
        "topology": "internal",
        "screensaver": True,
        "timeout": 120,
    }

    ret = main(["--mode", "normal", "--timeout", "120"])
    assert ret == 0

    mock_display_manager.apply_mode.assert_called_once_with(
        AppMode.NORMAL, timeout_seconds=120
    )
    captured = capsys.readouterr()
    assert "normal" in captured.out.lower()


def test_mode_failure_returns_one(mock_display_manager, capsys):
    """Test that failure in apply_mode prints to stderr and returns 1."""
    mock_display_manager.apply_mode.return_value = {
        "success": False,
        "mode": AppMode.PRESENTATION,
        "topology": None,
        "screensaver": None,
        "timeout": None,
    }

    ret = main(["--mode", "presentation"])
    assert ret == 1

    captured = capsys.readouterr()
    assert "error" in captured.err.lower()


def test_mode_exception_returns_one(mock_display_manager, capsys):
    """Test that an unhandled exception during apply_mode prints to stderr and returns 1."""
    mock_display_manager.apply_mode.side_effect = RuntimeError("Win32 error")

    ret = main(["--mode", "presentation"])
    assert ret == 1

    captured = capsys.readouterr()
    assert "error" in captured.err.lower()
    assert "win32 error" in captured.err.lower()


def test_mode_with_json_flag(mock_display_manager, capsys):
    """Test that --mode ... --json outputs JSON result directly."""
    mock_display_manager.apply_mode.return_value = {
        "success": True,
        "mode": AppMode.PRESENTATION,
        "topology": "external",
        "screensaver": False,
        "timeout": None,
    }

    ret = main(["--mode", "presentation", "--json"])
    assert ret == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["success"] is True
    assert data["mode"] == "presentation"
    assert data["topology"] == "external"


def test_mode_failure_with_json_flag(mock_display_manager, capsys):
    """Test that failure in --mode ... --json outputs error in JSON or stderr and returns 1."""
    mock_display_manager.apply_mode.return_value = {
        "success": False,
        "mode": AppMode.PRESENTATION,
        "topology": None,
        "screensaver": None,
        "timeout": None,
    }

    ret = main(["--mode", "presentation", "--json"])
    assert ret == 1

    captured = capsys.readouterr()
    assert len(captured.err) > 0


def test_invalid_mode_returns_error_code(capsys):
    """Test that an invalid mode choice returns code 2 or 1."""
    ret = main(["--mode", "supermode"])
    assert ret in (1, 2)


def test_unknown_argument_returns_error_code(capsys):
    """Test that unknown arguments return code 2 or 1."""
    ret = main(["--unknown-argument"])
    assert ret in (1, 2)


def test_default_launch_invokes_gui(mock_hdmi_app):
    """Test that running with no arguments initializes HdmiSelectorApp and calls mainloop."""
    mock_cls, mock_inst = mock_hdmi_app

    ret = main([])
    assert ret == 0
    mock_cls.assert_called_once()
    mock_inst.mainloop.assert_called_once()


def test_gui_flag_invokes_gui(mock_hdmi_app):
    """Test that --gui explicitly initializes HdmiSelectorApp and calls mainloop."""
    mock_cls, mock_inst = mock_hdmi_app

    ret = main(["--gui"])
    assert ret == 0
    mock_cls.assert_called_once()
    mock_inst.mainloop.assert_called_once()


def test_gui_launch_exception_returns_one(mock_hdmi_app, capsys):
    """Test that if GUI initialization or mainloop crashes, main() returns 1."""
    mock_cls, mock_inst = mock_hdmi_app
    mock_inst.mainloop.side_effect = RuntimeError("Tkinter init failed")

    ret = main(["--gui"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "error" in captured.err.lower()


def test_main_uses_sys_argv_when_argv_none(mock_display_manager, mock_app_config):
    """Test that main() defaults to sys.argv when argv is None."""
    with patch("sys.argv", ["hdmi-selector", "--status"]):
        ret = main()
        assert ret == 0


def test_help_flag_returns_zero(capsys):
    """Test that --help prints usage information and returns 0."""
    ret = main(["--help"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "hdmi-selector" in captured.out.lower() or "usage" in captured.out.lower()


def test_status_exception_returns_one(mock_display_manager, mock_app_config, capsys):
    """Test that an exception while querying status returns 1."""
    mock_display_manager.get_active_display_technologies.side_effect = RuntimeError("Hardware query error")

    ret = main(["--status"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "error" in captured.err.lower()
    assert "hardware query error" in captured.err.lower()


def test_module_execution_runpy():
    """Test executing HDMI_selector.main as __main__ using runpy."""
    import runpy
    import HDMI_selector.main as main_mod

    with patch("sys.argv", ["hdmi-selector", "--help"]), pytest.raises(SystemExit) as exc:
        runpy.run_path(main_mod.__file__, run_name="__main__")
    assert exc.value.code == 0



