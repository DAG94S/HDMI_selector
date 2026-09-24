from unittest.mock import MagicMock, call
import pytest

from HDMI_selector.core.display_manager import (
    AppMode,
    DisplayManager,
    ERROR_SUCCESS,
    SDC_APPLY,
    SDC_TOPOLOGY_INTERNAL,
    SDC_TOPOLOGY_CLONE,
    SDC_TOPOLOGY_EXTEND,
    SDC_TOPOLOGY_EXTERNAL,
    OUTPUT_TECHNOLOGY_HDMI,
    SPI_SETSCREENSAVEACTIVE,
    SPI_SETSCREENSAVETIMEOUT,
    SPI_GETSCREENSAVEACTIVE,
    SPI_GETSCREENSAVETIMEOUT,
    SPIF_UPDATEINIFILE,
    SPIF_SENDCHANGE,
)


@pytest.fixture
def mock_user32():
    return MagicMock()


@pytest.fixture
def mock_winreg():
    return MagicMock()


def test_app_mode_teacher_enum_value():
    assert AppMode.TEACHER.value == "teacher"
    assert AppMode("teacher") == AppMode.TEACHER


def test_apply_mode_teacher_success(mock_user32, mock_winreg):
    dm = DisplayManager(user32=mock_user32, winreg_module=mock_winreg)
    mock_user32.SetDisplayConfig.return_value = ERROR_SUCCESS
    mock_user32.SystemParametersInfoW.return_value = 1

    result = dm.apply_mode(AppMode.TEACHER)
    assert result["success"] is True
    assert result["mode"] == AppMode.TEACHER
    assert result["topology"] == "extend"
    assert result["screensaver"] is False


def test_apply_mode_teacher_topology_failure(mock_user32, mock_winreg):
    dm = DisplayManager(user32=mock_user32, winreg_module=mock_winreg)
    mock_user32.SetDisplayConfig.return_value = 1  # Failure

    result = dm.apply_mode(AppMode.TEACHER)
    assert result["success"] is False
    assert result["mode"] == AppMode.TEACHER
    assert result["topology"] is None


def test_constants_and_enum():
    assert AppMode.PRESENTATION == "presentation"
    assert AppMode.EXERCISES == "exercises"
    assert AppMode.NORMAL == "normal"

    assert SDC_TOPOLOGY_INTERNAL == 0x00000001
    assert SDC_TOPOLOGY_CLONE == 0x00000002
    assert SDC_TOPOLOGY_EXTEND == 0x00000004
    assert SDC_TOPOLOGY_EXTERNAL == 0x00000008
    assert SDC_APPLY == 0x00000080
    assert OUTPUT_TECHNOLOGY_HDMI == 5


def test_set_display_topology():
    mock_user32 = MagicMock()
    mock_user32.SetDisplayConfig.return_value = 0  # ERROR_SUCCESS

    dm = DisplayManager(user32=mock_user32)
    result = dm.set_display_topology(SDC_TOPOLOGY_EXTERNAL)

    assert result is True
    mock_user32.SetDisplayConfig.assert_called_once_with(
        0, None, 0, None, SDC_APPLY | SDC_TOPOLOGY_EXTERNAL
    )

    # Test failure return code
    mock_user32.SetDisplayConfig.return_value = 1
    assert dm.set_display_topology(SDC_TOPOLOGY_INTERNAL) is False


def test_set_screensaver():
    mock_user32 = MagicMock()
    mock_user32.SystemParametersInfoW.return_value = 1

    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.HKEY_CURRENT_USER = 0x80000001
    mock_winreg.REG_SZ = 1
    mock_winreg.KEY_SET_VALUE = 0x0002

    dm = DisplayManager(user32=mock_user32, winreg_module=mock_winreg)

    # Disable screensaver
    success = dm.set_screensaver(active=False)
    assert success is True

    flags = SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    mock_user32.SystemParametersInfoW.assert_has_calls([
        call(SPI_SETSCREENSAVEACTIVE, 0, None, flags),
        call(SPI_SETSCREENSAVETIMEOUT, 60, None, flags),
    ])
    mock_winreg.SetValueEx.assert_has_calls([
        call(mock_key, "ScreenSaveActive", 0, 1, "0"),
        call(mock_key, "ScreenSaveTimeOut", 0, 1, "60"),
    ])

    # Enable screensaver with custom timeout
    mock_user32.reset_mock()
    mock_winreg.reset_mock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key

    success = dm.set_screensaver(active=True, timeout_seconds=180)
    assert success is True

    mock_user32.SystemParametersInfoW.assert_has_calls([
        call(SPI_SETSCREENSAVEACTIVE, 1, None, flags),
        call(SPI_SETSCREENSAVETIMEOUT, 180, None, flags),
    ])
    mock_winreg.SetValueEx.assert_has_calls([
        call(mock_key, "ScreenSaveActive", 0, 1, "1"),
        call(mock_key, "ScreenSaveTimeOut", 0, 1, "180"),
    ])


def test_set_screensaver_spi_success_registry_warning():
    mock_user32 = MagicMock()
    mock_user32.SystemParametersInfoW.return_value = 1

    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = PermissionError("Registry write denied")

    dm = DisplayManager(user32=mock_user32, winreg_module=mock_winreg)
    # Even if registry fails, SPI succeeded so screensaver call returns True
    success = dm.set_screensaver(active=True, timeout_seconds=60)
    assert success is True


def test_get_screensaver_state_from_registry():
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.side_effect = [("1", 1), ("120", 1)]

    dm = DisplayManager(winreg_module=mock_winreg)
    state = dm.get_screensaver_state()

    assert state == {"active": True, "timeout": 120}


def test_get_screensaver_state_fallback_spi():
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = OSError("Registry inaccessible")

    mock_user32 = MagicMock()

    def fake_spi(action, uiparam, pvparam, flags):
        if action == SPI_GETSCREENSAVEACTIVE:
            pvparam._obj.value = 1
            return 1
        elif action == SPI_GETSCREENSAVETIMEOUT:
            pvparam._obj.value = 90
            return 1
        return 0

    mock_user32.SystemParametersInfoW.side_effect = fake_spi

    dm = DisplayManager(user32=mock_user32, winreg_module=mock_winreg)
    state = dm.get_screensaver_state()

    assert state == {"active": True, "timeout": 90}


def test_apply_mode_presentation():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)

    result = dm.apply_mode(AppMode.PRESENTATION)

    dm.set_display_topology.assert_called_once_with(SDC_TOPOLOGY_EXTERNAL)
    dm.set_screensaver.assert_called_once_with(active=False)
    assert result == {
        "success": True,
        "mode": AppMode.PRESENTATION,
        "topology": "external",
        "screensaver": False,
        "timeout": None,
    }


def test_apply_mode_exercises():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)

    result = dm.apply_mode(AppMode.EXERCISES)

    dm.set_display_topology.assert_called_once_with(SDC_TOPOLOGY_EXTEND)
    dm.set_screensaver.assert_called_once_with(active=False)
    assert result == {
        "success": True,
        "mode": AppMode.EXERCISES,
        "topology": "extend",
        "screensaver": False,
        "timeout": None,
    }


def test_apply_mode_normal():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)

    result = dm.apply_mode(AppMode.NORMAL, timeout_seconds=45)

    dm.set_display_topology.assert_called_once_with(SDC_TOPOLOGY_INTERNAL)
    dm.set_screensaver.assert_called_once_with(active=True, timeout_seconds=45)
    assert result == {
        "success": True,
        "mode": AppMode.NORMAL,
        "topology": "internal",
        "screensaver": True,
        "timeout": 45,
    }


def test_apply_mode_with_string_and_invalid_mode():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)

    # String input converts to AppMode
    res = dm.apply_mode("presentation")
    assert res["mode"] == AppMode.PRESENTATION
    assert res["success"] is True
    assert res["timeout"] is None

    with pytest.raises(ValueError):
        dm.apply_mode("invalid_mode")


def test_apply_mode_guard_screensaver_on_presentation_failure():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=False)
    dm.set_screensaver = MagicMock()

    result = dm.apply_mode(AppMode.PRESENTATION)

    # Screensaver must NOT be disabled to protect OLED panel
    dm.set_screensaver.assert_not_called()
    assert result == {
        "success": False,
        "mode": AppMode.PRESENTATION,
        "topology": None,
        "screensaver": None,
        "timeout": None,
    }


def test_apply_mode_guard_screensaver_on_exercises_failure():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=False)
    dm.set_screensaver = MagicMock()

    result = dm.apply_mode(AppMode.EXERCISES)

    # Screensaver must NOT be disabled to protect OLED panel
    dm.set_screensaver.assert_not_called()
    assert result == {
        "success": False,
        "mode": AppMode.EXERCISES,
        "topology": None,
        "screensaver": None,
        "timeout": None,
    }


def test_apply_mode_normal_topology_failure():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=False)
    dm.set_screensaver = MagicMock(return_value=True)

    result = dm.apply_mode(AppMode.NORMAL, timeout_seconds=60)
    assert result == {
        "success": False,
        "mode": AppMode.NORMAL,
        "topology": None,
        "screensaver": True,
        "timeout": 60,
    }



def test_is_hdmi_connected():
    dm = DisplayManager()

    # Active HDMI technology (5)
    dm.get_active_display_technologies = MagicMock(return_value=[5])
    assert dm.is_hdmi_connected() is True

    # HDMI with internal laptop display
    dm.get_active_display_technologies = MagicMock(return_value=[-2147483648, 5])
    assert dm.is_hdmi_connected() is True

    # Other external monitor technology (10 = DisplayPort, 0 = VGA)
    dm.get_active_display_technologies = MagicMock(return_value=[10])
    assert dm.is_hdmi_connected() is True

    dm.get_active_display_technologies = MagicMock(return_value=[0])
    assert dm.is_hdmi_connected() is True

    # Only internal displays
    dm.get_active_display_technologies = MagicMock(return_value=[-2147483648])
    assert dm.is_hdmi_connected() is False

    dm.get_active_display_technologies = MagicMock(return_value=[6])
    assert dm.is_hdmi_connected() is False

    dm.get_active_display_technologies = MagicMock(return_value=[6, -2147483648])
    assert dm.is_hdmi_connected() is False

    # Empty list
    dm.get_active_display_technologies = MagicMock(return_value=[])
    assert dm.is_hdmi_connected() is False

    # Passing explicit technologies list without mocking
    assert dm.is_hdmi_connected([5]) is True
    assert dm.is_hdmi_connected([-2147483648]) is False


def test_readable_display_names_mapping():
    dm = DisplayManager()

    dm.get_active_display_technologies = MagicMock(
        return_value=[-2147483648, 5, 10, 0, 6, 999]
    )
    names = dm.get_active_display_names()

    assert names == [
        "Internal/Laptop",
        "HDMI",
        "DisplayPort",
        "VGA",
        "Internal/Laptop",
        "Unknown (999)",
    ]

    # Explicit argument
    assert dm.get_active_display_names([5]) == ["HDMI"]
    assert dm.get_active_display_names([]) == []


def test_get_active_display_technologies_with_mock_user32():
    mock_user32 = MagicMock()
    mock_user32.GetDisplayConfigBufferSizes.return_value = 1  # Failure

    dm = DisplayManager(user32=mock_user32)
    assert dm.get_active_display_technologies() == []


def test_get_active_display_technologies_zero_paths():
    mock_user32 = MagicMock()

    def fake_buffer_sizes(flags, p_paths, p_modes):
        p_paths._obj.value = 0
        p_modes._obj.value = 0
        return 0

    mock_user32.GetDisplayConfigBufferSizes.side_effect = fake_buffer_sizes
    dm = DisplayManager(user32=mock_user32)
    assert dm.get_active_display_technologies() == []


def test_get_active_display_technologies_query_fail():
    mock_user32 = MagicMock()

    def fake_buffer_sizes(flags, p_paths, p_modes):
        p_paths._obj.value = 1
        p_modes._obj.value = 1
        return 0

    mock_user32.GetDisplayConfigBufferSizes.side_effect = fake_buffer_sizes
    mock_user32.QueryDisplayConfig.return_value = 1  # Failure

    dm = DisplayManager(user32=mock_user32)
    assert dm.get_active_display_technologies() == []


def test_get_active_display_technologies_success_ctypes():
    mock_user32 = MagicMock()

    def fake_buffer_sizes(flags, p_paths, p_modes):
        p_paths._obj.value = 2
        p_modes._obj.value = 2
        return 0

    def fake_query(flags, p_paths, paths, p_modes, modes, top):
        paths[0].targetInfo.outputTechnology = 5  # HDMI
        paths[1].targetInfo.outputTechnology = -2147483648  # Internal
        return 0

    mock_user32.GetDisplayConfigBufferSizes.side_effect = fake_buffer_sizes
    mock_user32.QueryDisplayConfig.side_effect = fake_query

    dm = DisplayManager(user32=mock_user32)
    techs = dm.get_active_display_technologies()
    assert techs == [5, -2147483648]


def test_get_active_display_technologies_exception_handling():
    mock_user32 = MagicMock()
    mock_user32.GetDisplayConfigBufferSizes.side_effect = RuntimeError("Fatal error")

    dm = DisplayManager(user32=mock_user32)
    assert dm.get_active_display_technologies() == []


def test_null_subsystems_handling():
    dm = DisplayManager(user32=None, winreg_module=None)
    dm._user32 = None
    dm._winreg = None

    assert dm.get_active_display_technologies() == []
    assert dm.set_display_topology(SDC_TOPOLOGY_EXTERNAL) is False
    assert dm.set_screensaver(active=True) is False
    assert dm.get_screensaver_state() == {"active": False, "timeout": 60}


def test_set_display_topology_exception():
    mock_user32 = MagicMock()
    mock_user32.SetDisplayConfig.side_effect = RuntimeError("SetDisplayConfig crashed")

    dm = DisplayManager(user32=mock_user32)
    assert dm.set_display_topology(SDC_TOPOLOGY_EXTERNAL) is False


def test_set_screensaver_exceptions():
    mock_user32 = MagicMock()
    mock_user32.SystemParametersInfoW.side_effect = RuntimeError("SPI failed")

    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = RuntimeError("Winreg failed")

    dm = DisplayManager(user32=mock_user32, winreg_module=mock_winreg)
    assert dm.set_screensaver(active=True) is False


def test_real_windows_host_smoke_test():
    dm = DisplayManager()
    # Smoke test on the current host Windows machine
    techs = dm.get_active_display_technologies()
    assert isinstance(techs, list)
    names = dm.get_active_display_names(techs)
    assert isinstance(names, list)
    assert len(names) == len(techs)
    connected = dm.is_hdmi_connected(techs)
    assert isinstance(connected, bool)


def test_api_signatures_configured():
    dm = DisplayManager()
    if dm._user32 is not None:
        assert hasattr(dm._user32.SetDisplayConfig, "argtypes")
        assert len(dm._user32.SetDisplayConfig.argtypes) == 5
        assert hasattr(dm._user32.SystemParametersInfoW, "argtypes")
        assert len(dm._user32.SystemParametersInfoW.argtypes) == 4
        assert hasattr(dm._user32.GetDisplayConfigBufferSizes, "argtypes")
        assert len(dm._user32.GetDisplayConfigBufferSizes.argtypes) == 3
        assert hasattr(dm._user32.QueryDisplayConfig, "argtypes")
        assert len(dm._user32.QueryDisplayConfig.argtypes) == 6


