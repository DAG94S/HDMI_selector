"""Unit tests for HdmiSelectorApp UI component."""

import os
from unittest.mock import MagicMock, Mock, patch
import pytest
import customtkinter

from HDMI_selector.core.config import AppConfig
from HDMI_selector.core.display_manager import AppMode, DisplayManager
from HDMI_selector.core.hdmi_monitor import HdmiMonitor
from HDMI_selector.core.oled_curtain import OledCurtain
from HDMI_selector.ui.app import HdmiSelectorApp


@pytest.fixture
def mock_config(tmp_path):
    """Provides an AppConfig instance with a temp config file."""
    config_file = str(tmp_path / "test_config.json")
    cfg = AppConfig(
        screensaver_timeout=60,
        default_mode="normal",
        theme="dark",
        poll_interval_seconds=3,
        auto_restore_on_disconnect=True,
        config_path=config_file,
    )
    return cfg


@pytest.fixture
def mock_display_manager():
    """Provides a mocked DisplayManager."""
    dm = Mock(spec=DisplayManager)
    dm.get_active_display_technologies.return_value = [6, 5]
    dm.is_hdmi_connected.return_value = True
    dm.get_active_display_names.return_value = ["Internal/Laptop", "HDMI"]
    dm.set_display_topology.return_value = True
    dm.set_screensaver.return_value = True
    dm.apply_mode.return_value = {"success": True, "mode": AppMode.NORMAL}
    return dm


@pytest.fixture
def mock_monitor(mock_display_manager):
    """Provides a mocked HdmiMonitor."""
    mon = Mock(spec=HdmiMonitor)
    mon.display_manager = mock_display_manager
    mon.is_running.return_value = False
    mon.last_status = True
    mon.last_display_names = ["Internal/Laptop", "HDMI"]
    mon.current_mode = AppMode.NORMAL
    mon.auto_restore = True
    mon.poll_once.return_value = (True, ["Internal/Laptop", "HDMI"])
    return mon


@pytest.fixture
def mock_curtain():
    """Provides a mocked OledCurtain."""
    curtain = Mock(spec=OledCurtain)
    curtain.is_running.return_value = False
    curtain.timeout_seconds = 30
    return curtain


def _safe_destroy(app):
    """Safely cancels all pending Tcl after callbacks and destroys the app."""
    try:
        if app:
            if getattr(app, "teacher_curtain", None) and hasattr(app.teacher_curtain, "is_running") and app.teacher_curtain.is_running():
                app.teacher_curtain.stop()
            if getattr(app, "tk", None):
                for after_id in app.tk.call("after", "info"):
                    try:
                        app.after_cancel(after_id)
                    except Exception:
                        pass
                app.destroy()
    except Exception:
        pass


def _create_app(**kwargs):
    """Instantiates HdmiSelectorApp with retry to handle Windows Tcl teardown latency."""
    import time
    for attempt in range(3):
        try:
            return HdmiSelectorApp(**kwargs)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.15)


@pytest.fixture
def app_instance(mock_config, mock_display_manager, mock_monitor):
    """Creates a HdmiSelectorApp instance with withdrawn window and mock deps."""
    app = _create_app(
        config=mock_config,
        display_manager=mock_display_manager,
        monitor=mock_monitor,
        start_monitor=False,
        withdraw=True,
    )
    yield app
    _safe_destroy(app)


@pytest.fixture
def app_with_curtain(mock_config, mock_display_manager, mock_monitor, mock_curtain):
    """Creates a HdmiSelectorApp instance with injected mock_curtain."""
    app = _create_app(
        config=mock_config,
        display_manager=mock_display_manager,
        monitor=mock_monitor,
        teacher_curtain=mock_curtain,
        start_monitor=False,
        withdraw=True,
    )
    yield app
    _safe_destroy(app)


class TestHdmiSelectorAppInit:
    """Tests for HdmiSelectorApp initialization."""

    def test_init_default_instances(self):
        """App creates default config, display_manager and monitor if not supplied."""
        with patch("HDMI_selector.ui.app.HdmiMonitor") as MockMon:
            mon_instance = MockMon.return_value
            mon_instance.is_running.return_value = False
            mon_instance.last_status = False
            mon_instance.last_display_names = ["Internal/Laptop"]
            mon_instance.current_mode = AppMode.NORMAL
            mon_instance.poll_once.return_value = (False, ["Internal/Laptop"])

            app = _create_app(start_monitor=False, withdraw=True)
            try:
                assert isinstance(app.config, AppConfig)
                assert isinstance(app.display_manager, DisplayManager)
                assert app.monitor == mon_instance
            finally:
                _safe_destroy(app)

    def test_init_with_mocked_dependencies(self, app_instance, mock_config, mock_display_manager, mock_monitor):
        """App initializes with supplied dependencies and wires monitor callback."""
        assert app_instance.config == mock_config
        assert app_instance.display_manager == mock_display_manager
        assert app_instance.monitor == mock_monitor
        # Verify status change callback was connected
        assert mock_monitor.on_status_change is not None
        assert callable(mock_monitor.on_status_change)
        # Verify initial status was queried
        mock_monitor.poll_once.assert_called()

    def test_start_monitor_called_if_not_running(self, mock_config, mock_display_manager, mock_monitor):
        """If start_monitor is True and monitor is not running, start() is called."""
        mock_monitor.is_running.return_value = False
        app = _create_app(
            config=mock_config,
            display_manager=mock_display_manager,
            monitor=mock_monitor,
            start_monitor=True,
            withdraw=True,
        )
        try:
            mock_monitor.start.assert_called_once()
        finally:
            _safe_destroy(app)


class TestHdmiSelectorAppModeSelection:
    """Tests for selecting modes and button interactions."""

    def test_select_mode_presentation_when_connected(self, app_instance, mock_display_manager, mock_monitor, mock_config):
        """Selecting presentation mode when HDMI is connected applies mode without confirmation."""
        mock_monitor.last_status = True
        res = app_instance.select_mode(AppMode.PRESENTATION)

        assert res.get("success") is True
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.PRESENTATION, timeout_seconds=mock_config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.PRESENTATION
        assert mock_config.default_mode == "presentation"

        # Check visual card state
        pres_card = app_instance.mode_cards[AppMode.PRESENTATION]
        assert pres_card["badge"].cget("text") == "[ACTIVO]"
        assert pres_card["button"].cget("state") == "disabled"

        norm_card = app_instance.mode_cards[AppMode.NORMAL]
        assert norm_card["badge"].cget("text") == ""
        assert norm_card["button"].cget("state") == "normal"

    def test_select_mode_presentation_unconnected_cancel(self, app_instance, mock_display_manager, mock_monitor, mocker):
        """Selecting presentation mode when disconnected prompts user; cancelling aborts."""
        mock_monitor.last_status = False
        mock_display_manager.is_hdmi_connected.return_value = False
        mock_askyesno = mocker.patch("tkinter.messagebox.askyesno", return_value=False)

        res = app_instance.select_mode(AppMode.PRESENTATION)

        mock_askyesno.assert_called_once()
        mock_display_manager.apply_mode.assert_not_called()
        assert res.get("cancelled") is True
        assert mock_monitor.current_mode != AppMode.PRESENTATION

    def test_select_mode_presentation_unconnected_confirm(self, app_instance, mock_display_manager, mock_monitor, mocker):
        """Selecting presentation mode when disconnected prompts user; confirming applies mode."""
        mock_monitor.last_status = False
        mock_display_manager.is_hdmi_connected.return_value = False
        mock_askyesno = mocker.patch("tkinter.messagebox.askyesno", return_value=True)

        res = app_instance.select_mode(AppMode.PRESENTATION)

        mock_askyesno.assert_called_once()
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.PRESENTATION, timeout_seconds=app_instance.config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.PRESENTATION

    def test_select_mode_exercises(self, app_instance, mock_display_manager, mock_monitor, mock_config):
        """Selecting exercises mode applies extend topology."""
        res = app_instance.select_mode(AppMode.EXERCISES)

        assert res.get("success") is True
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.EXERCISES, timeout_seconds=mock_config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.EXERCISES
        assert mock_config.default_mode == "exercises"

        ex_card = app_instance.mode_cards[AppMode.EXERCISES]
        assert ex_card["badge"].cget("text") == "[ACTIVO]"
        assert ex_card["button"].cget("state") == "disabled"

    def test_select_mode_normal(self, app_instance, mock_display_manager, mock_monitor, mock_config):
        """Selecting normal mode applies internal topology and screensaver."""
        # First set to exercises
        mock_monitor.current_mode = AppMode.EXERCISES
        app_instance._update_mode_cards_visual(AppMode.EXERCISES)

        res = app_instance.select_mode(AppMode.NORMAL)

        assert res.get("success") is True
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.NORMAL, timeout_seconds=mock_config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.NORMAL
        assert mock_config.default_mode == "normal"

        norm_card = app_instance.mode_cards[AppMode.NORMAL]
        assert norm_card["badge"].cget("text") == "[ACTIVO]"
        assert norm_card["button"].cget("state") == "disabled"

    def test_card_buttons_invoke(self, app_instance, mock_display_manager, mock_monitor):
        """Clicking buttons directly on the cards triggers select_mode."""
        # Click exercises button
        app_instance.mode_cards[AppMode.EXERCISES]["button"].invoke()
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.EXERCISES, timeout_seconds=app_instance.config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.EXERCISES


class TestHdmiSelectorAppThreadSafety:
    """Tests for thread safety and status updates."""

    def test_status_change_dispatched_via_after(self, app_instance, mocker):
        """Background callback schedules UI update via self.after."""
        mock_after = mocker.spy(app_instance, "after")

        # Invoke the callback set on monitor
        app_instance._on_hdmi_status_threadsafe(True, ["Internal/Laptop", "HDMI"])

        # Must have called after(0, ...)
        assert mock_after.called
        assert mock_after.call_args[0][0] == 0

    def test_on_hdmi_status_changed_connected_ui(self, app_instance):
        """UI updates to green badge when HDMI connects."""
        app_instance._on_hdmi_status_changed(True, ["Internal/Laptop", "HDMI"])

        assert "HDMI Conectado" in app_instance.status_pill.cget("text")
        assert "●" in app_instance.status_pill.cget("text")
        assert "HDMI" in app_instance.displays_label.cget("text")

    def test_on_hdmi_status_changed_disconnected_ui(self, app_instance):
        """UI updates to amber badge when HDMI disconnects."""
        app_instance._on_hdmi_status_changed(False, ["Internal/Laptop"])

        assert "HDMI Desconectado" in app_instance.status_pill.cget("text")
        assert "○" in app_instance.status_pill.cget("text")
        assert "Internal/Laptop" in app_instance.displays_label.cget("text")

    def test_on_hdmi_status_changed_auto_restore_updates_cards(self, app_instance, mock_monitor, mock_config):
        """If monitor's mode became NORMAL due to auto-restore, cards reflect NORMAL."""
        mock_monitor.current_mode = AppMode.NORMAL
        mock_config.default_mode = "presentation"

        app_instance._on_hdmi_status_changed(False, ["Internal/Laptop"])

        norm_card = app_instance.mode_cards[AppMode.NORMAL]
        assert norm_card["badge"].cget("text") == "[ACTIVO]"
        assert mock_config.default_mode == "normal"


class TestHdmiSelectorAppConfigSettings:
    """Tests for the footer configuration controls."""

    def test_timeout_selection_updates_config(self, app_instance, mock_config, mock_display_manager, mock_monitor):
        """Changing screensaver timeout updates AppConfig and applies screensaver if in normal mode."""
        mock_monitor.current_mode = AppMode.NORMAL
        app_instance._on_timeout_selected("5 min")

        assert mock_config.screensaver_timeout == 300
        mock_display_manager.set_screensaver.assert_called_with(active=True, timeout_seconds=300)

    def test_auto_restore_toggle(self, app_instance, mock_config, mock_monitor):
        """Toggling auto-restore updates monitor and config."""
        app_instance.auto_restore_var.set(False)
        app_instance._on_auto_restore_toggled()

        assert mock_monitor.auto_restore is False
        assert mock_config.auto_restore_on_disconnect is False

        app_instance.auto_restore_var.set(True)
        app_instance._on_auto_restore_toggled()

        assert mock_monitor.auto_restore is True
        assert mock_config.auto_restore_on_disconnect is True

    def test_theme_change(self, app_instance, mock_config, mocker):
        """Changing theme calls set_appearance_mode and updates config."""
        mock_set_appearance = mocker.patch("customtkinter.set_appearance_mode")

        app_instance._on_theme_changed("Claro")

        mock_set_appearance.assert_called_with("light")
        assert mock_config.theme == "light"

        app_instance._on_theme_changed("Oscuro")

        mock_set_appearance.assert_called_with("dark")
        assert mock_config.theme == "dark"

    def test_manual_refresh_button(self, app_instance, mock_monitor):
        """Clicking Actualizar re-polls monitor and updates UI."""
        mock_monitor.poll_once.return_value = (True, ["Internal/Laptop", "External 4K"])

        connected, names = app_instance.refresh_status()

        assert connected is True
        assert "External 4K" in names
        assert "HDMI Conectado" in app_instance.status_pill.cget("text")
        assert "External 4K" in app_instance.displays_label.cget("text")


class TestHdmiSelectorAppWindowClosing:
    """Tests for window closing and resource cleanup."""

    def test_on_closing_stops_monitor_and_saves_config(self, app_instance, mock_monitor, mock_config, mocker):
        """Closing window stops monitor, saves config, and destroys window."""
        mock_save = mocker.spy(mock_config, "save")
        mock_destroy = mocker.patch.object(app_instance, "destroy")

        app_instance._on_closing()

        mock_monitor.stop.assert_called_once()
        assert mock_save.called
        mock_destroy.assert_called_once()

    def test_closing_handles_monitor_stop_exception(self, app_instance, mock_monitor, mock_config, mocker):
        """Closing window handles exceptions during monitor stop gracefully."""
        mock_monitor.stop.side_effect = RuntimeError("Thread error")
        mock_save = mocker.spy(mock_config, "save")
        mock_destroy = mocker.patch.object(app_instance, "destroy")

        app_instance._on_closing()

        assert mock_save.called
        mock_destroy.assert_called_once()


class TestHdmiSelectorAppEdgeCases:
    """Tests for edge cases and custom configuration values."""

    def test_custom_config_initialization(self, tmp_path, mock_display_manager, mock_monitor):
        """App initializes controls correctly with non-default config values."""
        cfg = AppConfig(
            screensaver_timeout=120,
            default_mode="exercises",
            theme="light",
            poll_interval_seconds=5,
            auto_restore_on_disconnect=False,
            config_path=str(tmp_path / "custom.json"),
        )
        mock_monitor.current_mode = AppMode.EXERCISES
        app = _create_app(
            config=cfg,
            display_manager=mock_display_manager,
            monitor=mock_monitor,
            start_monitor=False,
            withdraw=True,
        )
        try:
            assert app.timeout_menu.get() == "2 min"
            assert app.theme_menu.get() == "Claro"
            assert app.auto_restore_var.get() is False
            ex_card = app.mode_cards[AppMode.EXERCISES]
            assert ex_card["badge"].cget("text") == "[ACTIVO]"
        finally:
            _safe_destroy(app)

    def test_select_mode_exception_handled(self, app_instance, mock_display_manager, mocker):
        """If apply_mode raises an unexpected exception, UI shows error dialog and returns dict."""
        mock_display_manager.apply_mode.side_effect = RuntimeError("Win32 failure")
        mock_error = mocker.patch("tkinter.messagebox.showerror")

        res = app_instance.select_mode(AppMode.EXERCISES)

        mock_error.assert_called_once()
        assert res.get("success") is False
        assert "Win32 failure" in res.get("error", "")

    def test_select_mode_apply_mode_failed_dict(self, app_instance, mock_display_manager, mocker):
        """If apply_mode returns success=False, UI shows error dialog and does not set card active."""
        mock_display_manager.apply_mode.return_value = {"success": False, "error": "CCD rejected"}
        mock_error = mocker.patch("tkinter.messagebox.showerror")

        # Previous active mode was NORMAL
        assert app_instance.monitor.current_mode == AppMode.NORMAL
        res = app_instance.select_mode(AppMode.EXERCISES)

        mock_error.assert_called_once()
        assert res.get("success") is False
        # Card should not have switched to active
        ex_card = app_instance.mode_cards[AppMode.EXERCISES]
        assert ex_card["badge"].cget("text") == ""
        assert app_instance.monitor.current_mode == AppMode.NORMAL

    def test_startup_fallback_from_presentation_when_no_hdmi(
        self, tmp_path, mock_display_manager, mock_monitor
    ):
        """If default_mode is presentation but HDMI is disconnected, fallback to NORMAL."""
        cfg = AppConfig(
            default_mode="presentation",
            config_path=str(tmp_path / "pres_cfg.json"),
        )
        mock_monitor.last_status = False
        mock_monitor.current_mode = None
        mock_display_manager.is_hdmi_connected.return_value = False

        app = _create_app(
            config=cfg,
            display_manager=mock_display_manager,
            monitor=mock_monitor,
            start_monitor=False,
            withdraw=True,
        )
        try:
            assert app.monitor.current_mode == AppMode.NORMAL
            normal_card = app.mode_cards[AppMode.NORMAL]
            assert normal_card["badge"].cget("text") == "[ACTIVO]"
        finally:
            _safe_destroy(app)

    def test_startup_with_teacher_mode_starts_curtain(
        self, tmp_path, mock_display_manager, mock_monitor
    ):
        """If default_mode is teacher and HDMI is connected, app starts teacher_curtain."""
        cfg = AppConfig(
            default_mode="teacher",
            config_path=str(tmp_path / "teach_cfg.json"),
        )
        mock_monitor.last_status = True
        mock_monitor.current_mode = None
        mock_display_manager.is_hdmi_connected.return_value = True

        mock_curtain = Mock(spec=OledCurtain)
        mock_curtain.is_running.return_value = False
        mock_curtain.timeout_seconds = 30

        app = _create_app(
            config=cfg,
            display_manager=mock_display_manager,
            monitor=mock_monitor,
            teacher_curtain=mock_curtain,
            start_monitor=False,
            withdraw=True,
        )
        try:
            assert app.monitor.current_mode == AppMode.TEACHER
            teach_card = app.mode_cards[AppMode.TEACHER]
            assert teach_card["badge"].cget("text") == "[ACTIVO]"
            mock_curtain.start.assert_called_once()
        finally:
            _safe_destroy(app)

    def test_startup_fallback_from_teacher_when_no_hdmi(
        self, tmp_path, mock_display_manager, mock_monitor
    ):
        """If default_mode is teacher but HDMI is disconnected, fallback to NORMAL without starting curtain."""
        cfg = AppConfig(
            default_mode="teacher",
            config_path=str(tmp_path / "teach_no_hdmi.json"),
        )
        mock_monitor.last_status = False
        mock_monitor.current_mode = None
        mock_display_manager.is_hdmi_connected.return_value = False

        mock_curtain = Mock(spec=OledCurtain)
        mock_curtain.is_running.return_value = False

        app = _create_app(
            config=cfg,
            display_manager=mock_display_manager,
            monitor=mock_monitor,
            teacher_curtain=mock_curtain,
            start_monitor=False,
            withdraw=True,
        )
        try:
            assert app.monitor.current_mode == AppMode.NORMAL
            normal_card = app.mode_cards[AppMode.NORMAL]
            assert normal_card["badge"].cget("text") == "[ACTIVO]"
            mock_curtain.start.assert_not_called()
        finally:
            _safe_destroy(app)

    def test_destroy_stops_running_monitor(self, tmp_path, mock_display_manager):
        """Direct call to destroy() stops a running monitor thread."""
        cfg = AppConfig(config_path=str(tmp_path / "destroy_cfg.json"))
        mon = Mock(spec=HdmiMonitor)
        mon.last_status = True
        mon.last_display_names = ["HDMI"]
        mon.current_mode = AppMode.NORMAL
        mon.is_running.return_value = True

        app = _create_app(
            config=cfg,
            display_manager=mock_display_manager,
            monitor=mon,
            start_monitor=False,
            withdraw=True,
        )
        _safe_destroy(app)
        mon.stop.assert_called_once()

    def test_center_window_calls_geometry(self, app_instance):
        """_center_window uses native geometry and maintains proper window dimensions."""
        with patch.object(app_instance, "geometry") as mock_geom:
            app_instance._center_window(540, 660)
            mock_geom.assert_called_once()
            geom_str = mock_geom.call_args[0][0]
            assert "540x660" in geom_str
            assert "+" in geom_str

    def test_center_window_fallback_on_win32_failure(self, app_instance):
        """_center_window falls back cleanly when win32 raises an exception."""
        with patch("ctypes.windll.user32.GetCursorPos", side_effect=RuntimeError("Win32 error")), \
             patch.object(app_instance, "geometry") as mock_geom:
            app_instance._center_window(540, 660)
            mock_geom.assert_called_once()
            geom_str = mock_geom.call_args[0][0]
            assert "540x660" in geom_str


class TestHdmiSelectorAppTeacherMode:
    """Tests for Teacher Mode (Modo Docente) and OLED curtain integration in HdmiSelectorApp."""

    def test_mode_card_teacher_exists(self, app_instance):
        """AppMode.TEACHER exists in app.mode_cards with proper text and button."""
        assert AppMode.TEACHER in app_instance.mode_cards
        teacher_card = app_instance.mode_cards[AppMode.TEACHER]
        assert teacher_card["default_button_text"] == "Activar Modo Docente"
        assert teacher_card["button"].cget("text") == "Activar Modo Docente"

    def test_select_mode_teacher_when_connected(
        self, app_with_curtain, mock_display_manager, mock_monitor, mock_config, mock_curtain
    ):
        """Selecting AppMode.TEACHER when HDMI connected applies mode, updates cards, and starts curtain."""
        mock_monitor.last_status = True
        mock_display_manager.apply_mode.return_value = {
            "success": True,
            "mode": AppMode.TEACHER,
            "topology": "extend",
            "screensaver": False,
        }

        res = app_with_curtain.select_mode(AppMode.TEACHER)

        assert res.get("success") is True
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.TEACHER, timeout_seconds=mock_config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.TEACHER
        assert mock_config.default_mode == "teacher"

        # Check visual card state
        teacher_card = app_with_curtain.mode_cards[AppMode.TEACHER]
        assert teacher_card["badge"].cget("text") == "[ACTIVO]"
        assert teacher_card["button"].cget("state") == "disabled"

        # Verify curtain was started
        mock_curtain.start.assert_called_once()

    def test_switch_from_teacher_to_normal_stops_curtain(
        self, app_with_curtain, mock_display_manager, mock_monitor, mock_curtain
    ):
        """Switching from AppMode.TEACHER to AppMode.NORMAL calls teacher_curtain.stop()."""
        mock_monitor.current_mode = AppMode.TEACHER
        mock_curtain.is_running.return_value = True

        res = app_with_curtain.select_mode(AppMode.NORMAL)

        assert res.get("success") is True
        mock_curtain.stop.assert_called_once()
        assert mock_monitor.current_mode == AppMode.NORMAL

    def test_hdmi_disconnect_stops_curtain(self, app_with_curtain, mock_curtain):
        """Disconnecting HDMI stops teacher_curtain if it was running."""
        mock_curtain.is_running.return_value = True

        app_with_curtain._on_hdmi_status_changed(False, ["Internal/Laptop"])

        mock_curtain.stop.assert_called_once()

    def test_on_closing_stops_curtain(self, app_with_curtain, mock_curtain, mocker):
        """Closing the window calls teacher_curtain.stop()."""
        mock_curtain.is_running.return_value = True
        mocker.patch.object(app_with_curtain, "destroy")

        app_with_curtain._on_closing()

        mock_curtain.stop.assert_called_once()

    def test_destroy_stops_curtain(self, app_with_curtain, mock_curtain):
        """Calling destroy() calls teacher_curtain.stop()."""
        mock_curtain.is_running.return_value = True

        app_with_curtain.destroy()

        mock_curtain.stop.assert_called_once()

    def test_teacher_timeout_dropdown_updates_config_and_curtain(
        self, app_with_curtain, mock_config, mock_curtain
    ):
        """Selecting teacher timeout in dropdown updates config.teacher_timeout_seconds and curtain."""
        assert hasattr(app_with_curtain, "teacher_timeout_menu")

        app_with_curtain._on_teacher_timeout_selected("15 seg")
        assert mock_config.teacher_timeout_seconds == 15
        assert mock_curtain.timeout_seconds == 15

        app_with_curtain._on_teacher_timeout_selected("1 min")
        assert mock_config.teacher_timeout_seconds == 60
        assert mock_curtain.timeout_seconds == 60

    def test_select_mode_teacher_unconnected_cancel(
        self, app_with_curtain, mock_display_manager, mock_monitor, mock_curtain, mocker
    ):
        """Selecting teacher mode when disconnected prompts user; cancelling aborts without starting curtain."""
        mock_monitor.last_status = False
        mock_display_manager.is_hdmi_connected.return_value = False
        mock_askyesno = mocker.patch("tkinter.messagebox.askyesno", return_value=False)

        res = app_with_curtain.select_mode(AppMode.TEACHER)

        mock_askyesno.assert_called_once()
        mock_display_manager.apply_mode.assert_not_called()
        mock_curtain.start.assert_not_called()
        assert res.get("cancelled") is True
        assert mock_monitor.current_mode != AppMode.TEACHER

    def test_select_mode_teacher_unconnected_confirm(
        self, app_with_curtain, mock_display_manager, mock_monitor, mock_curtain, mocker
    ):
        """Selecting teacher mode when disconnected prompts user; confirming applies mode and starts curtain."""
        mock_monitor.last_status = False
        mock_display_manager.is_hdmi_connected.return_value = False
        mock_askyesno = mocker.patch("tkinter.messagebox.askyesno", return_value=True)

        res = app_with_curtain.select_mode(AppMode.TEACHER)

        mock_askyesno.assert_called_once()
        mock_display_manager.apply_mode.assert_called_with(
            AppMode.TEACHER, timeout_seconds=app_with_curtain.config.screensaver_timeout
        )
        assert mock_monitor.current_mode == AppMode.TEACHER
        mock_curtain.start.assert_called_once()

    def test_default_teacher_curtain_initialization(
        self, mock_config, mock_display_manager, mock_monitor
    ):
        """HdmiSelectorApp initializes default OledCurtain with config timeout if not injected."""
        app = _create_app(
            config=mock_config,
            display_manager=mock_display_manager,
            monitor=mock_monitor,
            start_monitor=False,
            withdraw=True,
        )
        try:
            assert hasattr(app, "teacher_curtain")
            assert isinstance(app.teacher_curtain, OledCurtain)
            assert app.teacher_curtain.timeout_seconds == mock_config.teacher_timeout_seconds
        finally:
            _safe_destroy(app)


