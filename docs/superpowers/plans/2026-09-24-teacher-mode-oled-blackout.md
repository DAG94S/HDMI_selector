# Teacher Mode (Modo Docente) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a dedicated Teacher Mode ("Modo Docente") for HDMI Selector that maintains extended desktop to an external projector while blanking the OLED laptop display with a pure black (`#000000`) topmost curtain that turns OLED pixels physically off, waking instantly only when the cursor enters the laptop display and auto-blacking out after inactivity.

**Architecture:** A new `AppMode.TEACHER` is added to `DisplayManager` (applying `SDC_TOPOLOGY_EXTEND` and disabling screensaver). A dedicated, thread-safe `OledCurtain` service in `core/oled_curtain.py` creates a borderless topmost `#000000` window sized to the primary/laptop monitor boundaries via Win32 `EnumDisplayMonitors`. A low-overhead polling loop checks `GetCursorPos()`, hiding the curtain when the cursor enters the laptop monitor and showing it when inactivity exceeds `teacher_timeout_seconds`. The CustomTkinter UI in `ui/app.py` exposes a 4th mode card with live state and a timeout dropdown in quick settings.

**Architecture Diagram:**

```mermaid
graph TD
    subgraph UI ["HDMI Selector GUI & CLI"]
        App["HdmiSelectorApp (ui/app.py)"]
        CLI["CLI --mode teacher (main.py)"]
        Settings["Quick Settings (teacher_timeout_seconds)"]
    end

    subgraph Core ["Core Services"]
        Config["AppConfig (core/config.py)"]
        DM["DisplayManager (core/display_manager.py)"]
        Curtain["OledCurtain (core/oled_curtain.py)"]
        Monitor["HdmiMonitor (core/hdmi_monitor.py)"]
    end

    subgraph Win32 ["Windows Subsystem"]
        SDC["SetDisplayConfig(SDC_TOPOLOGY_EXTEND)"]
        Cursor["GetCursorPos() / EnumDisplayMonitors()"]
        Overlay["HWND_TOPMOST #000000 Window (Monitor 1)"]
    end

    App -->|select_mode('teacher')| DM
    CLI -->|apply_mode('teacher')| DM
    Settings -->|update timeout| Config
    DM -->|Apply topology| SDC
    App -->|start/stop| Curtain
    Curtain -->|Enumerate rect| Cursor
    Curtain -->|Create/Show/Hide| Overlay
    Monitor -->|On disconnect -> stop| Curtain
```

**Tech Stack:** Python 3.14+, `ctypes` (Win32 User32 APIs), `customtkinter`, `pytest`, `pytest-mock`.

## Global Constraints
- Target OS: Windows 10/11 64-bit.
- OLED Blackout window background color: `#000000` (RGB 0,0,0) with `HWND_TOPMOST` and `WS_EX_TOOLWINDOW`.
- Topologies: `SDC_TOPOLOGY_EXTEND` (0x00000004) when in Teacher Mode.
- No third-party mouse-hook dependencies (use Win32 `GetCursorPos` via `ctypes.windll.user32`).
- Safe fallback: Always destroy curtain immediately on HDMI disconnect or application close.

---

### Task 1: Environment & Configuration Updates

**Files:**
- Create: `conftest.py`
- Modify: [core/config.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/core/config.py)
- Modify: [tests/test_config.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/tests/test_config.py)
- Modify: [tests/test_main.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/tests/test_main.py)

**Interfaces:**
- `AppConfig`: adds `teacher_timeout_seconds: int = 30` attribute with JSON serialization/deserialization.

- [ ] **Step 1: Write failing tests in `tests/test_config.py` and fix `test_main.py` test environment**

Add test for `teacher_timeout_seconds` in `tests/test_config.py`:
```python
def test_teacher_timeout_seconds_default_and_persistence(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg = AppConfig(config_path=str(cfg_file))
    assert cfg.teacher_timeout_seconds == 30

    cfg.teacher_timeout_seconds = 15
    cfg.save()

    cfg2 = AppConfig(config_path=str(cfg_file))
    cfg2.load()
    assert cfg2.teacher_timeout_seconds == 15
```

Fix assertion in `tests/test_main.py` around line 74:
Change `assert data["config"]["screensaver_timeout"] == 60` to match `mock_app_config.screensaver_timeout`.

Create `conftest.py` to auto-configure `TCL_LIBRARY` and `TK_LIBRARY` if missing in python environment:
```python
import os
import sys
import pathlib

# Ensure TCL_LIBRARY and TK_LIBRARY are set for Windows Python 3.14 environments
base_p = pathlib.Path(sys.base_prefix)
tcl_dir = base_p / "tcl" / "tcl8.6"
tk_dir = base_p / "tcl" / "tk8.6"
if tcl_dir.exists() and "TCL_LIBRARY" not in os.environ:
    os.environ["TCL_LIBRARY"] = str(tcl_dir)
if tk_dir.exists() and "TK_LIBRARY" not in os.environ:
    os.environ["TK_LIBRARY"] = str(tk_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -k "test_teacher_timeout" -v`
Expected: FAIL (`AttributeError: 'AppConfig' object has no attribute 'teacher_timeout_seconds'`)

- [ ] **Step 3: Update `AppConfig` in `core/config.py`**

In [core/config.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/core/config.py):
Add `teacher_timeout_seconds: int = 30` to `@dataclass AppConfig`.
Update `load()` to check `data.get("teacher_timeout_seconds")`.
Update `save()` to include `"teacher_timeout_seconds": self.teacher_timeout_seconds`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add conftest.py core/config.py tests/test_config.py tests/test_main.py
git commit -m "feat(config): add teacher_timeout_seconds and configure tcl test env"
```

---

### Task 2: DisplayManager Support for Teacher Mode

**Files:**
- Modify: [core/display_manager.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/core/display_manager.py)
- Modify: [tests/test_display_manager.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/tests/test_display_manager.py)

**Interfaces:**
- `AppMode`: adds `TEACHER = "teacher"`.
- `DisplayManager.apply_mode(AppMode.TEACHER, timeout_seconds=...)`:
  - Calls `set_display_topology(SDC_TOPOLOGY_EXTEND)`.
  - Calls `set_screensaver(active=False)`.
  - Returns dict with `{"success": bool, "mode": AppMode.TEACHER, "topology": "extend", "screensaver": False, "timeout": None}`.

- [ ] **Step 1: Write failing test in `tests/test_display_manager.py`**

Add tests:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_display_manager.py -k "teacher" -v`
Expected: FAIL (`AttributeError: type object 'AppMode' has no attribute 'TEACHER'`)

- [ ] **Step 3: Implement `AppMode.TEACHER` in `core/display_manager.py`**

Update `AppMode`:
```python
class AppMode(str, Enum):
    PRESENTATION = "presentation"
    TEACHER = "teacher"
    EXERCISES = "exercises"
    NORMAL = "normal"
```

Update `apply_mode`:
```python
        elif mode == AppMode.TEACHER:
            if not self.set_display_topology(SDC_TOPOLOGY_EXTEND):
                logger.warning("Failed to switch topology to extend for teacher mode.")
                return {
                    "success": False,
                    "mode": mode,
                    "topology": None,
                    "screensaver": None,
                    "timeout": None,
                }
            ss_ok = self.set_screensaver(active=False)
            return {
                "success": bool(ss_ok),
                "mode": mode,
                "topology": "extend",
                "screensaver": False if ss_ok else None,
                "timeout": None,
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_display_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add core/display_manager.py tests/test_display_manager.py
git commit -m "feat(display): add AppMode.TEACHER support to DisplayManager"
```

---

### Task 3: OledCurtain Component Implementation

**Files:**
- Create: `core/oled_curtain.py`
- Create: `tests/test_oled_curtain.py`

**Interfaces:**
- `OledCurtain`:
  - `__init__(timeout_seconds: int = 30, on_state_change: Optional[Callable[[bool], None]] = None, user32=None)`
  - `start() -> None`: Starts cursor polling and creates window.
  - `stop() -> None`: Destroys window and joins thread.
  - `wake() -> None`: Hides blackout window.
  - `blackout() -> None`: Shows blackout window.
  - `is_blacked_out() -> bool`: Returns whether curtain is currently showing.
  - `get_primary_monitor_rect() -> tuple[int, int, int, int]`: Returns `(left, top, right, bottom)`.

- [ ] **Step 1: Write comprehensive unit tests in `tests/test_oled_curtain.py`**

Test monitor boundary detection, cursor hit testing, timeout expiration, wake/blackout transitions, and clean thread shutdown with mocks for `user32`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_oled_curtain.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'HDMI_selector.core.oled_curtain'`)

- [ ] **Step 3: Implement `core/oled_curtain.py`**

Implement:
1. `RECT` and `MONITORINFO` Win32 ctypes structures.
2. `get_primary_monitor_rect(user32)` using `EnumDisplayMonitors` / `GetMonitorInfoW` (defaults to virtual screen size `(0, 0, GetSystemMetrics(0), GetSystemMetrics(1))` if enumeration fails).
3. `OledCurtainWindow`: Pure Win32 window (or Tkinter Toplevel) styled with `#000000` background, borderless popup, `WS_EX_TOPMOST` and `WS_EX_TOOLWINDOW`.
4. Polling thread that checks cursor coordinates:
   - If `(x, y)` in primary monitor rect: call `wake()`, reset activity timer.
   - If `(x, y)` outside primary monitor (on projector): do not reset activity timer and do not wake.
   - When `time.time() - last_activity >= timeout_seconds` and awake: call `blackout()`.
5. Thread-safe locks and event cancellation.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_oled_curtain.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add core/oled_curtain.py tests/test_oled_curtain.py
git commit -m "feat(curtain): implement OledCurtain service with monitor-scoped cursor tracking"
```

---

### Task 4: CLI `--mode teacher` & `--status` Support

**Files:**
- Modify: [main.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/main.py)
- Modify: [tests/test_main.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/tests/test_main.py)

**Interfaces:**
- CLI parser: `--mode` allows `teacher` (`choices=["presentation", "teacher", "exercises", "normal"]`).
- `--status`: outputs `"teacher_timeout_seconds"` in the config block.

- [ ] **Step 1: Write failing test in `tests/test_main.py`**

```python
def test_cli_mode_teacher_invokes_apply_mode(mock_display_manager, mock_app_config):
    mock_display_manager.apply_mode.return_value = {
        "success": True, "mode": AppMode.TEACHER, "topology": "extend", "screensaver": False, "timeout": None
    }
    ret = main(["--mode", "teacher"])
    assert ret == 0
    mock_display_manager.apply_mode.assert_called_once_with(AppMode.TEACHER, timeout_seconds=60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -k "test_cli_mode_teacher" -v`
Expected: FAIL (`invalid choice: 'teacher'`)

- [ ] **Step 3: Update `main.py`**

1. Update `build_parser()` choices: `choices=["presentation", "teacher", "exercises", "normal"]`.
2. Update `--status` dictionary to report `teacher_timeout_seconds`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add main.py tests/test_main.py
git commit -m "feat(cli): support --mode teacher in CLI argument parser and status output"
```

---

### Task 5: CustomTkinter GUI Integration

**Files:**
- Modify: [ui/app.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/ui/app.py)
- Modify: [tests/test_ui_app.py](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/tests/test_ui_app.py)

**Interfaces:**
- `HdmiSelectorApp`:
  - Adds 4th mode card for `AppMode.TEACHER`.
  - Adds `teacher_curtain: Optional[OledCurtain]`.
  - Adds Quick Settings option menu for `teacher_timeout_seconds` (`15 seg`, `30 seg`, `1 min`).
  - Manages starting `OledCurtain` when `AppMode.TEACHER` is active, and stopping it when switching away or on closing.

- [ ] **Step 1: Write failing tests in `tests/test_ui_app.py`**

Add tests verifying:
1. `AppMode.TEACHER` exists in `app.mode_cards`.
2. Selecting `AppMode.TEACHER` activates card visual badge and starts curtain.
3. Switching from `TEACHER` to `NORMAL` stops curtain.
4. Changing teacher timeout dropdown updates `config.teacher_timeout_seconds`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_app.py -k "teacher" -v`
Expected: FAIL

- [ ] **Step 3: Update `ui/app.py`**

1. Import `OledCurtain`.
2. Add `AppMode.TEACHER` entry to `_build_mode_cards()`:
   - Title: `"Modo Docente (Clase interactiva)"`
   - Description: `"Diapositivas al 100% en proyector (HDMI extendido). Pantalla OLED apagada en reposo; se despierta al mover el mouse en la laptop y se apaga tras inactividad."`
   - Button text: `"Activar Modo Docente"`
3. Add teacher timeout control in `_build_quick_settings_footer()`.
4. In `select_mode(mode)`:
   - If new mode is `TEACHER`: start `self.teacher_curtain`.
   - If switching away from `TEACHER`: stop `self.teacher_curtain`.
5. In `_on_closing()`: ensure `self.teacher_curtain.stop()` is called.
6. In `_on_hdmi_status_changed()`: if disconnected, stop `self.teacher_curtain`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ui_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add ui/app.py tests/test_ui_app.py
git commit -m "feat(ui): add Teacher Mode card and OLED curtain controls to GUI"
```

---

### Task 6: Full Verification & Integration Test

**Files:**
- Entire repository

- [ ] **Step 1: Run complete pytest test suite**

Run: `pytest -v`
Expected: 100% tests PASS with zero errors.

- [ ] **Step 2: Verify CLI status command**

Run: `python main.py --status`
Expected: JSON output showing `is_hdmi_connected`, active displays, and config with `teacher_timeout_seconds`.

- [ ] **Step 3: Commit and update documentation**

Update README or docs if needed.
```bash
git commit -m "chore: complete verification for Teacher Mode with OLED curtain"
```
