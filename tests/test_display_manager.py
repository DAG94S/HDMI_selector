import ctypes
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
    QDC_ALL_PATHS,
    QDC_ONLY_ACTIVE_PATHS,
    ERROR_INSUFFICIENT_BUFFER,
    DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE,
    DISPLAYCONFIG_SOURCE_DEVICE_NAME,
    EXTERNAL_OUTPUT_TECHNOLOGIES,
    SET_TOPOLOGY_RETRY_DELAY,
    TOPOLOGY_VERIFY_POLLS,
)

INTERNAL = -2147483648


def _no_sleep(_seconds):
    return None


def make_fake_user32(paths_by_flag, modes=None, buffer_codes=None, query_codes=None):
    """Builds a MagicMock user32 whose QueryDisplayConfig returns the given paths.

    paths_by_flag: {flag: [dict(tech, target, source, available, adapter, src_mode)]}
    modes: list of dict(type, x, y, w, h) for source modes.
    buffer_codes / query_codes: optional lists of return codes consumed per call.
    """
    user32 = MagicMock()
    modes = modes or []
    buffer_codes = list(buffer_codes or [])
    query_codes = list(query_codes or [])

    def fake_buffer_sizes(flags, p_paths, p_modes):
        code = buffer_codes.pop(0) if buffer_codes else 0
        p_paths._obj.value = len(paths_by_flag.get(flags, []))
        p_modes._obj.value = len(modes)
        return code

    def fake_query(flags, p_paths, paths, p_modes, modes_arr, top):
        code = query_codes.pop(0) if query_codes else 0
        if code != 0:
            return code
        for i, spec in enumerate(paths_by_flag.get(flags, [])):
            path = paths[i]
            adapter = spec.get("adapter", (1, 0))
            path.targetInfo.adapterId.LowPart = adapter[0]
            path.targetInfo.adapterId.HighPart = adapter[1]
            path.sourceInfo.adapterId.LowPart = adapter[0]
            path.sourceInfo.adapterId.HighPart = adapter[1]
            path.targetInfo.id = spec.get("target", i)
            path.sourceInfo.id = spec.get("source", i)
            path.targetInfo.outputTechnology = spec["tech"]
            path.targetInfo.targetAvailable = 1 if spec.get("available", True) else 0
            path.sourceInfo.modeInfoIdx = spec.get("src_mode", 0xFFFFFFFF)
            path.flags = 1
        for j, m in enumerate(modes):
            modes_arr[j].infoType = m.get("type", DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE)
            sm = modes_arr[j].modeInfo.sourceMode
            sm.position.x = m["x"]
            sm.position.y = m["y"]
            sm.width = m["w"]
            sm.height = m["h"]
        return 0

    user32.GetDisplayConfigBufferSizes.side_effect = fake_buffer_sizes
    user32.QueryDisplayConfig.side_effect = fake_query
    return user32


@pytest.fixture
def mock_user32():
    return MagicMock()


@pytest.fixture
def mock_winreg():
    return MagicMock()


def test_app_mode_teacher_enum_value():
    assert AppMode.TEACHER.value == "teacher"
    assert AppMode("teacher") == AppMode.TEACHER


def test_apply_mode_teacher_success():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)

    result = dm.apply_mode(AppMode.TEACHER)

    dm.set_display_topology.assert_called_once_with(SDC_TOPOLOGY_EXTEND)
    dm.set_screensaver.assert_called_once_with(active=False)
    assert result == {
        "success": True,
        "mode": AppMode.TEACHER,
        "topology": "extend",
        "screensaver": False,
        "timeout": None,
        "topology_ok": True,
        "screensaver_ok": True,
    }
    assert result["timeout"] is None


def test_apply_mode_teacher_topology_failure():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=False)
    dm.set_screensaver = MagicMock()

    result = dm.apply_mode(AppMode.TEACHER)

    dm.set_screensaver.assert_not_called()
    assert result == {
        "success": False,
        "mode": AppMode.TEACHER,
        "topology": None,
        "screensaver": None,
        "timeout": None,
        "topology_ok": False,
        "screensaver_ok": False,
    }
    assert result["screensaver"] is None
    assert result["timeout"] is None


def test_apply_mode_guard_screensaver_on_teacher_failure():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=False)
    dm.set_screensaver = MagicMock()

    result = dm.apply_mode(AppMode.TEACHER)

    # Screensaver must NOT be disabled to protect OLED panel
    dm.set_screensaver.assert_not_called()
    assert result == {
        "success": False,
        "mode": AppMode.TEACHER,
        "topology": None,
        "screensaver": None,
        "timeout": None,
        "topology_ok": False,
        "screensaver_ok": False,
    }
    assert result["screensaver"] is None
    assert result["timeout"] is None


def test_constants_and_enum():
    assert AppMode.PRESENTATION == "presentation"
    assert AppMode.TEACHER == "teacher"
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

    dm = DisplayManager(user32=mock_user32, sleep_func=_no_sleep)
    result = dm.set_display_topology(SDC_TOPOLOGY_EXTERNAL)

    # Topology could not be read back (mock query fails) -> assumed applied
    assert result is True
    mock_user32.SetDisplayConfig.assert_called_once_with(
        0, None, 0, None, SDC_APPLY | SDC_TOPOLOGY_EXTERNAL
    )

    # Test failure return code: retried 3 times then False
    mock_user32.SetDisplayConfig.reset_mock()
    mock_user32.SetDisplayConfig.return_value = 1
    assert dm.set_display_topology(SDC_TOPOLOGY_INTERNAL) is False
    assert mock_user32.SetDisplayConfig.call_count == 3


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

    # Disable screensaver: only the active flag changes, user's timeout is preserved
    success = dm.set_screensaver(active=False)
    assert success is True

    flags = SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    mock_user32.SystemParametersInfoW.assert_called_once_with(
        SPI_SETSCREENSAVEACTIVE, 0, None, flags
    )
    mock_winreg.SetValueEx.assert_called_once_with(mock_key, "ScreenSaveActive", 0, 1, "0")

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
        "topology_ok": True,
        "screensaver_ok": True,
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
        "topology_ok": True,
        "screensaver_ok": True,
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
        "topology_ok": True,
        "screensaver_ok": True,
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

    res_teacher = dm.apply_mode("teacher")
    assert res_teacher["mode"] == AppMode.TEACHER
    assert res_teacher["success"] is True
    assert res_teacher["timeout"] is None

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
        "topology_ok": False,
        "screensaver_ok": False,
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
        "topology_ok": False,
        "screensaver_ok": False,
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
        "topology_ok": False,
        "screensaver_ok": True,
    }



def test_is_hdmi_connected():
    dm = DisplayManager()

    # Explicit technology lists
    assert dm.is_hdmi_connected([5]) is True
    assert dm.is_hdmi_connected([-2147483648, 5]) is True
    assert dm.is_hdmi_connected([10]) is True  # DisplayPort
    assert dm.is_hdmi_connected([0]) is True   # VGA
    assert dm.is_hdmi_connected([-2147483648]) is False
    assert dm.is_hdmi_connected([6]) is False
    assert dm.is_hdmi_connected([6, -2147483648]) is False
    assert dm.is_hdmi_connected([]) is False
    # Indirect virtual displays are not physical external screens
    assert dm.is_hdmi_connected([17]) is False

    # Query-based: available external targets
    dm.get_available_external_technologies = MagicMock(return_value=[5])
    assert dm.is_hdmi_connected() is True
    dm.get_available_external_technologies = MagicMock(return_value=[])
    assert dm.is_hdmi_connected() is False
    # Unknown state must never be reported as disconnected
    dm.get_available_external_technologies = MagicMock(return_value=None)
    assert dm.is_hdmi_connected() is None


def test_external_technologies_set():
    assert 17 not in EXTERNAL_OUTPUT_TECHNOLOGIES
    for tech in (0, 4, 5, 10, 16, 18):
        assert tech in EXTERNAL_OUTPUT_TECHNOLOGIES
    for tech in (6, 11, 13, -2147483648, -1):
        assert tech not in EXTERNAL_OUTPUT_TECHNOLOGIES


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

    dm = DisplayManager(user32=mock_user32, sleep_func=_no_sleep)
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
    assert dm.is_hdmi_connected() in (True, False, None)
    assert dm.get_current_topology() in ("internal", "external", "extend", "clone", None)
    names = dm.get_internal_display_device_names()
    assert names is None or all(isinstance(n, str) for n in names)


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




# ---------------------------------------------------------------------------
# QueryDisplayConfig robustness
# ---------------------------------------------------------------------------

def test_query_retries_on_insufficient_buffer():
    user32 = make_fake_user32(
        {QDC_ONLY_ACTIVE_PATHS: [{"tech": 5}, {"tech": INTERNAL}]},
        query_codes=[ERROR_INSUFFICIENT_BUFFER, 0],
    )
    dm = DisplayManager(user32=user32)
    assert dm.get_active_display_technologies() == [5, INTERNAL]
    assert user32.QueryDisplayConfig.call_count == 2


def test_query_buffer_sizes_insufficient_buffer_retry():
    user32 = make_fake_user32(
        {QDC_ALL_PATHS: [{"tech": 5, "available": True}]},
        buffer_codes=[ERROR_INSUFFICIENT_BUFFER, 0],
    )
    dm = DisplayManager(user32=user32)
    assert dm.is_hdmi_connected() is True
    assert user32.GetDisplayConfigBufferSizes.call_count == 2


def test_query_persistent_insufficient_buffer_is_unknown():
    user32 = make_fake_user32(
        {QDC_ALL_PATHS: [{"tech": 5}], QDC_ONLY_ACTIVE_PATHS: [{"tech": 5}]},
        query_codes=[ERROR_INSUFFICIENT_BUFFER] * 10,
    )
    dm = DisplayManager(user32=user32)
    assert dm.is_hdmi_connected() is None
    assert dm.get_current_topology() is None
    assert dm.get_active_display_technologies() == []


def test_is_hdmi_connected_api_error_returns_none():
    user32 = MagicMock()
    user32.GetDisplayConfigBufferSizes.return_value = 87  # ERROR_INVALID_PARAMETER
    dm = DisplayManager(user32=user32)
    assert dm.is_hdmi_connected() is None

    user32.GetDisplayConfigBufferSizes.side_effect = RuntimeError("boom")
    assert dm.is_hdmi_connected() is None


def test_is_hdmi_connected_zero_paths_is_unknown():
    user32 = make_fake_user32({QDC_ALL_PATHS: []})
    dm = DisplayManager(user32=user32)
    assert dm.is_hdmi_connected() is None


def test_is_hdmi_connected_uses_all_paths_and_target_available():
    # NORMAL mode: HDMI connected but INACTIVE -> only visible through QDC_ALL_PATHS
    user32 = make_fake_user32({
        QDC_ALL_PATHS: [
            {"tech": INTERNAL, "target": 1, "source": 0, "available": True},
            {"tech": 5, "target": 2, "source": 0, "available": True},
            {"tech": 5, "target": 2, "source": 1, "available": True},  # same target, other source
            {"tech": 10, "target": 3, "source": 0, "available": False},  # empty DP port
        ],
        QDC_ONLY_ACTIVE_PATHS: [{"tech": INTERNAL, "target": 1, "source": 0}],
    })
    dm = DisplayManager(user32=user32)
    assert dm.get_available_external_technologies() == [5]  # deduplicated
    assert dm.is_hdmi_connected() is True
    assert dm.get_active_display_names() == ["Internal/Laptop"]
    flags_used = {c.args[0] for c in user32.GetDisplayConfigBufferSizes.call_args_list}
    assert QDC_ALL_PATHS in flags_used


def test_is_hdmi_connected_false_when_no_external_available():
    user32 = make_fake_user32({
        QDC_ALL_PATHS: [
            {"tech": INTERNAL, "target": 1, "available": True},
            {"tech": 5, "target": 2, "available": False},
            {"tech": 17, "target": 3, "available": True},  # indirect virtual
        ],
    })
    dm = DisplayManager(user32=user32)
    assert dm.is_hdmi_connected() is False


def test_dedup_distinguishes_adapters():
    user32 = make_fake_user32({
        QDC_ALL_PATHS: [
            {"tech": 5, "target": 2, "adapter": (1, 0)},
            {"tech": 5, "target": 2, "adapter": (2, 0)},
        ],
    })
    dm = DisplayManager(user32=user32)
    assert dm.get_available_external_technologies() == [5, 5]


# ---------------------------------------------------------------------------
# Current topology / mode detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "active_paths, expected_topology, expected_mode",
    [
        ([{"tech": INTERNAL, "target": 1, "source": 0}], "internal", AppMode.NORMAL),
        ([{"tech": 5, "target": 2, "source": 0}], "external", AppMode.PRESENTATION),
        (
            [{"tech": INTERNAL, "target": 1, "source": 0}, {"tech": 5, "target": 2, "source": 1}],
            "extend",
            AppMode.EXERCISES,
        ),
        (
            [{"tech": INTERNAL, "target": 1, "source": 0}, {"tech": 5, "target": 2, "source": 0}],
            "clone",
            None,
        ),
        ([{"tech": 11, "target": 1, "source": 0}], "internal", AppMode.NORMAL),  # eDP
    ],
)
def test_get_current_topology_and_detect_mode(active_paths, expected_topology, expected_mode):
    user32 = make_fake_user32({QDC_ONLY_ACTIVE_PATHS: active_paths})
    dm = DisplayManager(user32=user32)
    assert dm.get_current_topology() == expected_topology
    assert dm.detect_current_mode() == expected_mode


def test_get_current_topology_unknown():
    user32 = MagicMock()
    user32.GetDisplayConfigBufferSizes.return_value = 31
    dm = DisplayManager(user32=user32)
    assert dm.get_current_topology() is None
    assert dm.detect_current_mode() is None

    empty = DisplayManager(user32=make_fake_user32({QDC_ONLY_ACTIVE_PATHS: []}))
    assert empty.get_current_topology() is None

    none_dm = DisplayManager(user32=None)
    none_dm._user32 = None
    assert none_dm.get_current_topology() is None


def _fake_device_info(names_by_source):
    """Fake DisplayConfigGetDeviceInfo writing viewGdiDeviceName by source id."""
    def fake(p_header):
        header = p_header._obj
        name = names_by_source.get(int(header.id))
        if name is None:
            return 31
        header._b_base_.viewGdiDeviceName = name
        return 0
    return fake


def test_get_internal_display_device_names():
    user32 = make_fake_user32({
        QDC_ONLY_ACTIVE_PATHS: [
            {"tech": 5, "target": 2, "source": 1},
            {"tech": INTERNAL, "target": 1, "source": 0},
        ]
    })
    user32.DisplayConfigGetDeviceInfo.side_effect = _fake_device_info(
        {0: "\\\\.\\DISPLAY1", 1: "\\\\.\\DISPLAY2"}
    )
    dm = DisplayManager(user32=user32)
    assert dm.get_internal_display_device_names() == ["\\\\.\\DISPLAY1"]
    header = user32.DisplayConfigGetDeviceInfo.call_args.args[0]._obj
    assert header.type == 1  # DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    assert header.size == ctypes.sizeof(DISPLAYCONFIG_SOURCE_DEVICE_NAME)


def test_get_internal_display_device_names_edge_cases():
    # Internal panel inactive (presentation mode) -> []
    user32 = make_fake_user32({QDC_ONLY_ACTIVE_PATHS: [{"tech": 5, "source": 0}]})
    user32.DisplayConfigGetDeviceInfo.side_effect = _fake_device_info({0: "X"})
    assert DisplayManager(user32=user32).get_internal_display_device_names() == []

    # DisplayConfigGetDeviceInfo failure -> skipped
    user32 = make_fake_user32({QDC_ONLY_ACTIVE_PATHS: [{"tech": INTERNAL, "source": 0}]})
    user32.DisplayConfigGetDeviceInfo.side_effect = _fake_device_info({})
    assert DisplayManager(user32=user32).get_internal_display_device_names() == []

    # Query failure -> unknown
    user32 = MagicMock()
    user32.GetDisplayConfigBufferSizes.return_value = 31
    assert DisplayManager(user32=user32).get_internal_display_device_names() is None


# ---------------------------------------------------------------------------
# set_display_topology retries and verification
# ---------------------------------------------------------------------------

def test_set_display_topology_retries_then_succeeds():
    user32 = make_fake_user32({QDC_ONLY_ACTIVE_PATHS: [{"tech": 5, "target": 2}]})
    user32.SetDisplayConfig.side_effect = [31, 31, 0]
    sleep = MagicMock()
    dm = DisplayManager(user32=user32, sleep_func=sleep)

    assert dm.set_display_topology(SDC_TOPOLOGY_EXTERNAL) is True
    assert user32.SetDisplayConfig.call_count == 3
    sleep.assert_has_calls([call(SET_TOPOLOGY_RETRY_DELAY), call(SET_TOPOLOGY_RETRY_DELAY)])


def test_set_display_topology_all_attempts_fail():
    user32 = MagicMock()
    user32.SetDisplayConfig.return_value = 31
    sleep = MagicMock()
    dm = DisplayManager(user32=user32, sleep_func=sleep)

    assert dm.set_display_topology(SDC_TOPOLOGY_EXTEND) is False
    assert user32.SetDisplayConfig.call_count == 3
    assert sleep.call_count == 2  # no pause after the last attempt


def test_set_display_topology_verification_polls_until_match():
    user32 = MagicMock()
    user32.SetDisplayConfig.return_value = 0
    dm = DisplayManager(user32=user32, sleep_func=_no_sleep)
    dm.get_current_topology = MagicMock(side_effect=[None, "internal", "extend"])

    assert dm.set_display_topology(SDC_TOPOLOGY_EXTEND) is True
    assert dm.get_current_topology.call_count == 3


def test_set_display_topology_verification_mismatch_fails():
    user32 = MagicMock()
    user32.SetDisplayConfig.return_value = 0
    sleep = MagicMock()
    dm = DisplayManager(user32=user32, sleep_func=sleep)
    dm.get_current_topology = MagicMock(return_value="internal")

    assert dm.set_display_topology(SDC_TOPOLOGY_EXTEND) is False
    assert dm.get_current_topology.call_count == TOPOLOGY_VERIFY_POLLS
    assert sleep.call_count == TOPOLOGY_VERIFY_POLLS - 1


def test_set_display_topology_verification_unknown_assumes_success():
    user32 = MagicMock()
    user32.SetDisplayConfig.return_value = 0
    dm = DisplayManager(user32=user32, sleep_func=_no_sleep)
    dm.get_current_topology = MagicMock(return_value=None)

    assert dm.set_display_topology(SDC_TOPOLOGY_INTERNAL) is True


def test_set_display_topology_end_to_end_with_fake_query():
    user32 = make_fake_user32({
        QDC_ONLY_ACTIVE_PATHS: [
            {"tech": INTERNAL, "target": 1, "source": 0},
            {"tech": 5, "target": 2, "source": 1},
        ]
    })
    user32.SetDisplayConfig.return_value = 0
    dm = DisplayManager(user32=user32, sleep_func=_no_sleep)
    assert dm.set_display_topology(SDC_TOPOLOGY_EXTEND) is True
    assert dm.set_display_topology(SDC_TOPOLOGY_CLONE) is False


# ---------------------------------------------------------------------------
# apply_mode success semantics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [AppMode.PRESENTATION, AppMode.TEACHER, AppMode.EXERCISES])
def test_apply_mode_screensaver_failure_does_not_fail_topology(mode):
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=False)

    result = dm.apply_mode(mode)
    assert result["success"] is True
    assert result["topology_ok"] is True
    assert result["screensaver_ok"] is False
    assert result["screensaver"] is None


def test_apply_mode_teacher_never_uses_external_topology():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)
    dm.apply_mode(AppMode.TEACHER)
    dm.set_display_topology.assert_called_once_with(SDC_TOPOLOGY_EXTEND)


def test_apply_mode_normal_screensaver_failure_still_success():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=False)

    result = dm.apply_mode(AppMode.NORMAL, timeout_seconds=300)
    assert result["success"] is True
    assert result["topology_ok"] is True
    assert result["screensaver_ok"] is False
    assert result["timeout"] is None
    dm.set_screensaver.assert_called_once_with(active=True, timeout_seconds=300)


def test_apply_mode_normal_invalid_timeout_falls_back():
    dm = DisplayManager()
    dm.set_display_topology = MagicMock(return_value=True)
    dm.set_screensaver = MagicMock(return_value=True)
    result = dm.apply_mode(AppMode.NORMAL, timeout_seconds=0)
    dm.set_screensaver.assert_called_once_with(active=True, timeout_seconds=60)
    assert result["timeout"] == 60
