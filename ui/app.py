"""Modern graphical user interface for HDMI Selector & OLED Saver."""

import ctypes
import logging
import queue
import threading
import tkinter.font as tkfont
from ctypes import wintypes
from tkinter import messagebox
from typing import Any, Callable, Optional

import customtkinter as ctk

from HDMI_selector.core.config import AppConfig
from HDMI_selector.core.display_manager import AppMode, DisplayManager
from HDMI_selector.core.hdmi_monitor import HdmiMonitor
from HDMI_selector.core.oled_curtain import OledCurtain

logger = logging.getLogger(__name__)

# Palette as (light, dark) tuples. Single accent colour.
C_BG = ("#F4F6FA", "#0F1115")
C_CARD = ("#FFFFFF", "#181B22")
C_CARD_HOVER = ("#EEF2F8", "#1F232C")
C_BORDER = ("#D8DDE8", "#2A2F3A")
C_TEXT = ("#1B1F29", "#E6E8EE")
C_TEXT_2 = ("#5B6475", "#8B93A5")
C_ACCENT = "#4C8DFF"
C_ACTIVE_FILL = ("#DCE8FF", "#1E3A6E")
C_OK = "#34D399"
C_WARN = "#F59E0B"

RADIUS = 12
SP_XS, SP_S, SP_M, SP_L = 4, 8, 12, 16

# mode -> (glyph, name, subtitle, long description, default button text)
MODE_INFO: dict[AppMode, tuple[str, str, str, str, str]] = {
    AppMode.PRESENTATION: (
        "\u25B6", "Presentaci\u00f3n", "Solo proyector",
        "Pantalla OLED apagada (protecci\u00f3n contra quemado). HDMI activo al 100%. Salvapantallas en pausa.",
        "Activar",
    ),
    AppMode.TEACHER: (
        "\u270E", "Docente", "Proyector + OLED en reposo",
        "Diapositivas al 100% en proyector (HDMI extendido). La pantalla OLED se apaga en reposo; "
        "se despierta al mover el mouse en la laptop y se apaga tras inactividad.",
        "Activar",
    ),
    AppMode.EXERCISES: (
        "\u25A6", "Ejercicios", "Ambas pantallas",
        "Escritorio extendido para resolver ejercicios con alumnos. Ambas pantallas encendidas. "
        "Salvapantallas en pausa.",
        "Activar",
    ),
    AppMode.NORMAL: (
        "\u2302", "Normal", "Solo laptop",
        "Pantalla de laptop \u00fanicamente. Salvapantallas activo tras inactividad para proteger el panel OLED.",
        "Restaurar",
    ),
}


class HdmiSelectorApp(ctk.CTk):
    """Main application window for HDMI Selector & OLED Saver."""

    TIMEOUT_OPTIONS: dict[str, int] = {
        "1 min": 60,
        "2 min": 120,
        "5 min": 300,
        "10 min": 600,
    }
    TIMEOUT_SECONDS_TO_CHOICE: dict[int, str] = {
        60: "1 min",
        120: "2 min",
        300: "5 min",
        600: "10 min",
    }
    TEACHER_TIMEOUT_OPTIONS: dict[str, int] = {
        "15 seg": 15,
        "30 seg": 30,
        "1 min": 60,
    }
    TEACHER_TIMEOUT_SECONDS_TO_CHOICE: dict[int, str] = {
        15: "15 seg",
        30: "30 seg",
        60: "1 min",
    }
    THEME_OPTIONS: dict[str, str] = {
        "Oscuro": "dark",
        "Claro": "light",
    }
    THEME_MAP_REVERSE: dict[str, str] = {
        "dark": "Oscuro",
        "light": "Claro",
    }

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        display_manager: Optional[DisplayManager] = None,
        monitor: Optional[HdmiMonitor] = None,
        teacher_curtain: Optional[OledCurtain] = None,
        start_monitor: bool = True,
        withdraw: bool = False,
        run_in_background: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        """Initializes the GUI application window and services.

        Args:
            config: Optional AppConfig instance. If None, creates and loads default.
            display_manager: Optional DisplayManager. If None, creates default.
            monitor: Optional HdmiMonitor. If None, creates default.
            teacher_curtain: Optional OledCurtain instance. If None, creates default.
            start_monitor: If True, starts the background monitor thread.
            withdraw: If True, withdraws window immediately (used in headless/tests).
            run_in_background: Optional executor ``fn -> None`` used for blocking
                work (mode switching, polling). Defaults to a daemon thread; tests
                inject a synchronous runner.
        """
        super().__init__()

        if withdraw:
            self.withdraw()

        self._closing = False
        self._switching = False
        self._ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._queue_after_id: Optional[str] = None
        self._toast_after_id: Optional[str] = None
        self._hdmi_connected: Optional[bool] = None
        self._active_mode: AppMode = AppMode.NORMAL
        self._hovered_mode: Optional[AppMode] = None
        self.last_result: Optional[dict] = None
        self._run_in_background: Callable[[Callable[[], None]], None] = (
            run_in_background or self._default_background_runner
        )

        if config is None:
            config = AppConfig()
            config.load()
        self.config = config

        if display_manager is None:
            display_manager = DisplayManager()
        self.display_manager = display_manager

        if monitor is None:
            kwargs: dict[str, Any] = dict(
                display_manager=self.display_manager,
                poll_interval=self.config.poll_interval_seconds,
                auto_restore=self.config.auto_restore_on_disconnect,
            )
            try:
                monitor = HdmiMonitor(
                    on_mode_restored=self._on_mode_restored_threadsafe,
                    timeout_provider=lambda: self.config.screensaver_timeout,
                    **kwargs,
                )
            except TypeError:
                monitor = HdmiMonitor(**kwargs)
        else:
            try:
                monitor.on_mode_restored = self._on_mode_restored_threadsafe
            except Exception:
                pass
        self.monitor = monitor
        self.monitor.on_status_change = self._on_hdmi_status_threadsafe

        if teacher_curtain is None:
            teacher_curtain = OledCurtain(
                timeout_seconds=self.config.teacher_timeout_seconds
            )
        self.teacher_curtain: Optional[OledCurtain] = teacher_curtain

        # Set appearance and styling
        ctk.set_appearance_mode(self.config.theme)
        ctk.set_default_color_theme("blue")

        try:
            families = set(tkfont.families(self))
        except Exception:
            families = set()
        self.font_family = "Segoe UI Variable" if "Segoe UI Variable" in families else "Segoe UI"

        self.title("HDMI Selector")
        self.configure(fg_color=C_BG)
        self.minsize(360, 420)
        self._center_window(420, 580)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Dictionary tracking card widgets
        self.mode_cards: dict[AppMode, dict[str, Any]] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Build UI layout
        self._build_header_and_status()
        self._build_tabs()
        self._build_mode_cards()
        self._build_quick_settings_footer()

        # Start background monitor if requested and not yet active
        if start_monitor and not self.monitor.is_running():
            self.monitor.start()

        # Start UI queue pump (background threads -> Tk thread)
        self._queue_after_id = self.after(50, self._poll_queue)

        # Query initial HDMI and displays status (background)
        self.refresh_status()

        # Set initial visual active card state (provisional, from config)
        initial_mode = (
            self.monitor.current_mode
            if self.monitor.current_mode is not None
            else self._parse_mode(self.config.default_mode)
        )
        if initial_mode in (AppMode.PRESENTATION, AppMode.TEACHER) and self.is_hdmi_connected is False:
            initial_mode = AppMode.NORMAL

        self.monitor.current_mode = initial_mode
        self._active_mode = initial_mode
        self._update_mode_cards_visual(initial_mode)
        self._render_status()

        # The curtain is NOT started here: HDMI status is still unknown at this
        # point, and blackening the only screen would leave the user in the dark.
        # _on_detected_mode starts it once the real topology is known.
        # Reconcile with the real Windows topology (background)
        self._sync_with_system()

    # ------------------------------------------------------------------
    # Threading helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _default_background_runner(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _post(self, fn: Callable[[], None]) -> None:
        """Thread-safe: schedules fn to run on the Tk thread."""
        self._ui_queue.put(fn)

    def _poll_queue(self) -> None:
        """Drains the UI queue and re-arms itself (runs on the Tk thread)."""
        self._queue_after_id = None
        self.process_pending()
        if not self._closing:
            try:
                self._queue_after_id = self.after(50, self._poll_queue)
            except Exception:
                self._queue_after_id = None

    def process_pending(self) -> None:
        """Runs all queued UI callbacks (Tk thread). Public so tests can pump it."""
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as e:
                logger.error("UI callback failed: %s", e)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def is_hdmi_connected(self) -> Optional[bool]:
        """True/False if HDMI/external display state is known, None if unknown."""
        if self.monitor.last_status is not None:
            return self.monitor.last_status
        return self.display_manager.is_hdmi_connected()

    @property
    def active_display_names(self) -> list[str]:
        """Returns list of active display names."""
        if self.monitor.last_display_names:
            return self.monitor.last_display_names
        return self.display_manager.get_active_display_names()

    # ------------------------------------------------------------------
    # Window geometry
    # ------------------------------------------------------------------
    def _center_window(self, width: int = 420, height: int = 580) -> None:
        """Sizes (capped to the work area) and centers the window on the active display."""
        try:
            scaling = float(self._get_window_scaling())
        except Exception:
            scaling = 1.0
        if scaling <= 0:
            scaling = 1.0

        def fit(work_w: int, work_h: int) -> tuple[int, int]:
            lw, lh = work_w / scaling, work_h / scaling
            return max(1, int(min(width, 0.9 * lw))), max(1, int(min(height, 0.85 * lh)))

        try:
            if hasattr(ctypes, "windll"):
                user32 = ctypes.windll.user32
                point = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(point)):
                    hmon = user32.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
                else:
                    hmon = None

                if hmon:
                    class MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", wintypes.DWORD),
                            ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD),
                        ]

                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                        work = mi.rcWork
                        work_w = work.right - work.left
                        work_h = work.bottom - work.top
                        w, h = fit(work_w, work_h)
                        x = work.left + max(0, (work_w - int(w * scaling)) // 2)
                        y = work.top + max(0, (work_h - int(h * scaling)) // 2)
                        self.geometry(f"{w}x{h}+{x}+{y}")
                        return
        except Exception as e:
            logger.debug("Win32 monitor centering fallback: %s", e)

        # Fallback to Tkinter screen metrics
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w, h = fit(sw, sh)
            x = max(0, (sw - int(w * scaling)) // 2)
            y = max(0, (sh - int(h * scaling)) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception as e:
            logger.debug("Tk geometry centering fallback: %s", e)
            self.geometry(f"{width}x{height}")

    def _parse_mode(self, mode_val: str) -> AppMode:
        """Parses a mode string into an AppMode enum safely."""
        try:
            return AppMode(mode_val)
        except (ValueError, KeyError):
            return AppMode.NORMAL

    def _font(self, size: int = 12, bold: bool = False) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.font_family, size=size, weight="bold" if bold else "normal")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_header_and_status(self) -> None:
        """Builds the compact status bar card (row 0)."""
        self.header_frame = ctk.CTkFrame(
            self, corner_radius=RADIUS, fg_color=C_CARD, border_width=1, border_color=C_BORDER
        )
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=SP_L, pady=(SP_L, SP_S))
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.status_pill = ctk.CTkLabel(
            self.header_frame,
            text="○ HDMI Desconectado",
            text_color=C_WARN,
            font=self._font(12, True),
            anchor="w",
        )
        self.status_pill.grid(row=0, column=0, sticky="w", padx=(SP_M, SP_S), pady=(SP_M, 0))

        self.refresh_btn = ctk.CTkButton(
            self.header_frame,
            text="⟳",
            width=28,
            height=28,
            corner_radius=8,
            font=self._font(14, True),
            fg_color="transparent",
            border_width=1,
            border_color=C_BORDER,
            text_color=C_TEXT,
            hover_color=C_CARD_HOVER,
            command=self.refresh_status,
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e", padx=(0, SP_M), pady=(SP_M, 0))

        self.displays_label = ctk.CTkLabel(
            self.header_frame,
            text="Pantallas: Detectando...",
            font=self._font(11),
            text_color=C_TEXT_2,
            anchor="w",
        )
        self.displays_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=SP_M, pady=(2, SP_M))

        # Transient toast / busy message (hidden when empty)
        self.toast_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=self._font(11, True),
            text_color=C_WARN,
            anchor="w",
            justify="left",
        )
        self.toast_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=SP_M, pady=(0, SP_M))
        self.toast_label.grid_remove()
        self.header_frame.bind("<Configure>", self._on_header_configure)

    def _on_header_configure(self, event: Any) -> None:
        try:
            scaling = float(self._get_window_scaling())
            self.toast_label.configure(wraplength=max(120, int(event.width / scaling) - 2 * SP_M))
        except Exception:
            pass

    def _build_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(
            self,
            corner_radius=RADIUS,
            fg_color=C_CARD,
            border_width=1,
            border_color=C_BORDER,
            segmented_button_fg_color=C_BG,
            segmented_button_selected_color=C_ACCENT,
            segmented_button_selected_hover_color=C_ACCENT,
            segmented_button_unselected_color=C_BG,
            segmented_button_unselected_hover_color=C_CARD_HOVER,
            text_color=C_TEXT,
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=SP_L, pady=(SP_S, SP_L))
        self.tab_modes = self.tabview.add("Modos")
        self.tab_settings = self.tabview.add("Ajustes")
        try:
            self.tabview._segmented_button.configure(font=self._font(12, True))
        except Exception:
            pass

    def _build_mode_cards(self) -> None:
        """Builds the 2x2 grid of mode tiles and the description label."""
        tab = self.tab_modes
        tab.grid_columnconfigure((0, 1), weight=1, uniform="tiles")
        self.cards_frame = tab

        order = [AppMode.PRESENTATION, AppMode.TEACHER, AppMode.EXERCISES, AppMode.NORMAL]
        for idx, mode in enumerate(order):
            glyph, name, subtitle, _desc, btn_text = MODE_INFO[mode]
            tile = ctk.CTkFrame(
                tab,
                corner_radius=RADIUS,
                border_width=1,
                border_color=C_BORDER,
                fg_color=C_CARD,
            )
            tile.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=SP_XS, pady=SP_XS)
            tab.grid_rowconfigure(idx // 2, weight=0)
            tile.grid_columnconfigure(0, weight=1)

            glyph_lbl = ctk.CTkLabel(
                tile, text=glyph, font=ctk.CTkFont(family="Segoe UI Symbol", size=18),
                text_color=C_ACCENT, anchor="w",
            )
            glyph_lbl.grid(row=0, column=0, sticky="w", padx=(SP_M, 0), pady=(SP_M, 0))

            badge_lbl = ctk.CTkLabel(
                tile, text="", font=self._font(11, True), text_color=C_OK, anchor="e"
            )
            badge_lbl.grid(row=0, column=0, sticky="e", padx=(0, SP_M), pady=(SP_M, 0))

            name_lbl = ctk.CTkLabel(
                tile, text=name, font=self._font(14, True), text_color=C_TEXT, anchor="w"
            )
            name_lbl.grid(row=1, column=0, sticky="w", padx=SP_M, pady=(2, 0))

            sub_lbl = ctk.CTkLabel(
                tile, text=subtitle, font=self._font(11), text_color=C_TEXT_2,
                anchor="w", justify="left", wraplength=140,
            )
            sub_lbl.grid(row=2, column=0, sticky="w", padx=SP_M, pady=(0, SP_S))

            action_btn = ctk.CTkButton(
                tile,
                text=btn_text,
                height=28,
                corner_radius=8,
                font=self._font(12, True),
                fg_color="transparent",
                border_width=1,
                border_color=C_ACCENT,
                text_color=C_ACCENT,
                hover_color=C_CARD_HOVER,
                command=lambda m=mode: self.select_mode(m),
            )
            action_btn.grid(row=3, column=0, sticky="ew", padx=SP_M, pady=(0, SP_M))

            for w in (tile, glyph_lbl, badge_lbl, name_lbl, sub_lbl):
                w.bind("<Button-1>", lambda _e, m=mode: self.select_mode(m), add="+")
            for w in (tile, glyph_lbl, badge_lbl, name_lbl, sub_lbl, action_btn):
                w.bind("<Enter>", lambda _e, m=mode: self._on_tile_hover(m), add="+")
                w.bind("<Leave>", lambda _e, m=mode: self._on_tile_leave(m), add="+")

            self.mode_cards[mode] = {
                "frame": tile,
                "badge": badge_lbl,
                "button": action_btn,
                "default_button_text": btn_text,
                "name": name_lbl,
                "subtitle": sub_lbl,
            }

        self.mode_desc_label = ctk.CTkLabel(
            tab,
            text="",
            font=self._font(11),
            text_color=C_TEXT_2,
            anchor="nw",
            justify="left",
            wraplength=300,
        )
        self.mode_desc_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=SP_S, pady=(SP_S, 0))
        tab.bind("<Configure>", self._on_modes_configure)
        self._refresh_description()

    def _on_modes_configure(self, event: Any) -> None:
        try:
            scaling = float(self._get_window_scaling())
            logical_w = int(event.width / scaling)
            self.mode_desc_label.configure(wraplength=max(120, logical_w - 2 * SP_L))
            sub_wrap = max(80, (logical_w - 4 * SP_L) // 2 - SP_M)
            for card in self.mode_cards.values():
                card["subtitle"].configure(wraplength=sub_wrap)
        except Exception:
            pass

    def _on_tile_hover(self, mode: AppMode) -> None:
        self._hovered_mode = mode
        card = self.mode_cards.get(mode)
        if card is not None and mode != self._active_mode:
            card["frame"].configure(fg_color=C_CARD_HOVER)
        self._refresh_description()

    def _on_tile_leave(self, mode: AppMode) -> None:
        if self._hovered_mode == mode:
            self._hovered_mode = None
        card = self.mode_cards.get(mode)
        if card is not None and mode != self._active_mode:
            card["frame"].configure(fg_color=C_CARD)
        self._refresh_description()

    def _refresh_description(self) -> None:
        """Shows the long description of the hovered mode, else of the active mode."""
        mode = self._hovered_mode or self._active_mode
        try:
            self.mode_desc_label.configure(text=MODE_INFO[mode][3])
        except Exception:
            pass

    def _build_quick_settings_footer(self) -> None:
        """Builds the 'Ajustes' tab: scrollable label|control rows."""
        self.settings_frame = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        self.settings_frame.pack(fill="both", expand=True)
        sf = self.settings_frame
        sf.grid_columnconfigure(0, weight=1)
        sf.grid_columnconfigure(1, weight=0)

        def label(row: int, text: str) -> None:
            ctk.CTkLabel(
                sf, text=text, font=self._font(12), text_color=C_TEXT, anchor="w"
            ).grid(row=row, column=0, sticky="w", padx=(SP_S, SP_S), pady=SP_S)

        def menu(row: int, values: list[str], command: Callable[[str], None], current: str):
            m = ctk.CTkOptionMenu(
                sf, values=values, width=96, height=28, font=self._font(12),
                dropdown_font=self._font(12), command=command,
                fg_color=C_ACCENT, button_color=C_ACCENT, button_hover_color=C_ACCENT,
            )
            m.set(current)
            m.grid(row=row, column=1, sticky="e", padx=(0, SP_S), pady=SP_S)
            return m

        label(0, "Salvapantallas")
        self.timeout_menu = menu(
            0, list(self.TIMEOUT_OPTIONS.keys()), self._on_timeout_selected,
            self.TIMEOUT_SECONDS_TO_CHOICE.get(self.config.screensaver_timeout, "1 min"),
        )

        label(1, "Reposo docente")
        self.teacher_timeout_menu = menu(
            1, list(self.TEACHER_TIMEOUT_OPTIONS.keys()), self._on_teacher_timeout_selected,
            self.TEACHER_TIMEOUT_SECONDS_TO_CHOICE.get(self.config.teacher_timeout_seconds, "30 seg"),
        )

        label(2, "Tema")
        self.theme_menu = menu(
            2, ["Oscuro", "Claro"], self._on_theme_changed,
            self.THEME_MAP_REVERSE.get(self.config.theme, "Oscuro"),
        )

        label(3, "Auto-restaurar")
        self.auto_restore_var = ctk.BooleanVar(value=self.config.auto_restore_on_disconnect)
        self.auto_restore_switch = ctk.CTkSwitch(
            sf,
            text="Volver a Normal si se desconecta el HDMI",
            font=self._font(11),
            text_color=C_TEXT_2,
            progress_color=C_ACCENT,
            variable=self.auto_restore_var,
            command=self._on_auto_restore_toggled,
        )
        self.auto_restore_switch.grid(row=4, column=0, columnspan=2, sticky="w", padx=SP_S, pady=(0, SP_S))

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------
    def select_mode(self, mode: AppMode | str) -> dict:
        """Starts applying an operational mode in the background.

        The blocking Windows topology change runs in a worker thread; the result is
        delivered through the UI queue (see ``_on_apply_done``). Returns immediately:
        ``{"success": None, "pending": True}`` when started, ``{"cancelled": True}``
        if the user declined the HDMI confirmation, ``{"busy": True}`` if another
        switch is already running.
        """
        if isinstance(mode, str):
            mode = self._parse_mode(mode)

        if self._switching:
            return {"success": False, "busy": True}

        # Confirm before activating presentation/teacher mode if HDMI is known to be absent.
        # An unknown state (None) never blocks.
        if mode != AppMode.NORMAL and self.is_hdmi_connected is False:
            if mode == AppMode.TEACHER:
                mode_desc = "Modo Docente"
                effect_desc = "la pantalla de la laptop se apagará automáticamente tras inactividad."
            elif mode == AppMode.PRESENTATION:
                mode_desc = "Modo Presentación"
                effect_desc = "la pantalla de la laptop se apagará de inmediato."
            else:
                mode_desc = None
                effect_desc = ""
            if mode_desc is not None:
                proceed = messagebox.askyesno(
                    "Confirmación HDMI",
                    "No se detecta ningún monitor HDMI o pantalla externa conectada.\n\n"
                    f"Si activa el {mode_desc}, {effect_desc}\n"
                    "¿Está seguro de que desea continuar?",
                    parent=self,
                )
                if not proceed:
                    return {"success": False, "cancelled": True}

        self._switching = True
        self._previous_mode = self._active_mode
        self._set_tiles_enabled(False)
        self._show_toast("⏳ Aplicando…", C_ACCENT, 0)

        # Stop the curtain BEFORE changing topology (it could blacken the projector).
        if mode != AppMode.TEACHER and self.teacher_curtain is not None:
            try:
                self.teacher_curtain.stop()
            except Exception as e:
                logger.warning("Error stopping teacher curtain before switch: %s", e)

        timeout = self.config.screensaver_timeout
        self._run_in_background(lambda: self._apply_worker(mode, timeout))
        return {"success": None, "pending": True, "mode": mode}

    def _apply_worker(self, mode: AppMode, timeout: int) -> None:
        """Runs in a worker thread. Never touches Tk; posts the result to the queue."""
        lock = getattr(self.monitor, "mode_lock", None)
        locked = False
        try:
            if lock is not None and hasattr(lock, "acquire"):
                lock.acquire()
                locked = True
            notify = getattr(self.monitor, "notify_mode_change", None)
            if callable(notify):
                try:
                    notify(mode)
                except Exception as e:
                    logger.debug("notify_mode_change failed: %s", e)
            res = self.display_manager.apply_mode(mode, timeout_seconds=timeout)
            err = None
        except Exception as e:
            logger.error("Error applying mode %s: %s", mode, e)
            res, err = None, e
        finally:
            if locked:
                try:
                    lock.release()
                except Exception:
                    pass
        self._post(lambda: self._on_apply_done(mode, res, err))

    def _on_apply_done(self, mode: AppMode, res: Any, err: Optional[Exception]) -> None:
        """Tk thread: handles the outcome of a mode switch."""
        self._switching = False
        self._hide_toast()

        if err is not None:
            result: dict = {"success": False, "error": str(err)}
            self.last_result = result
            self._fail_switch(mode, f"No se pudo aplicar el modo: {err}", title="Error")
            return

        if isinstance(res, dict):
            ok = res.get("topology_ok", res.get("success", False))
            result = res
        else:
            ok = bool(res)
            result = {"success": ok}
        self.last_result = result

        if not ok:
            logger.warning("apply_mode failed for mode %s: %s", mode, result)
            self._fail_switch(
                mode,
                f"No se pudo aplicar el modo {mode.value}.\n"
                "Verifique la conexión del cable HDMI o el estado de la pantalla externa.",
                title="Error al cambiar modo",
            )
            return

        self._active_mode = mode
        self.monitor.current_mode = mode
        self.config.default_mode = mode.value
        self.config.save()
        if mode == AppMode.TEACHER and self.teacher_curtain is not None:
            try:
                if not self.teacher_curtain.is_running():
                    self.teacher_curtain.start()
            except Exception as e:
                logger.warning("Error starting teacher curtain: %s", e)

        self._update_mode_cards_visual(mode)
        self._render_status()
        if result.get("screensaver_ok") is False:
            self._show_toast(
                "⚠ Modo aplicado, pero no se pudo configurar el salvapantallas.", C_WARN, 8000
            )

    def _fail_switch(self, mode: AppMode, message: str, title: str) -> None:
        previous = getattr(self, "_previous_mode", self._active_mode)
        self.monitor.current_mode = previous
        if previous == AppMode.TEACHER and mode != AppMode.TEACHER and self.teacher_curtain is not None:
            try:
                if not self.teacher_curtain.is_running():
                    self.teacher_curtain.start()
            except Exception as e:
                logger.warning("Error restarting teacher curtain: %s", e)
        self._update_mode_cards_visual(self._active_mode)
        self._render_status()
        messagebox.showerror(title, message, parent=self)
        self._sync_with_system()

    # ------------------------------------------------------------------
    # System state reconciliation
    # ------------------------------------------------------------------
    def _sync_with_system(self) -> None:
        """Detects the real Windows topology in the background and syncs the tiles."""
        detect = getattr(self.display_manager, "detect_current_mode", None)
        if not callable(detect):
            return

        def work() -> None:
            try:
                detected = detect()
            except Exception as e:
                logger.debug("detect_current_mode failed: %s", e)
                detected = None
            self._post(lambda: self._on_detected_mode(detected))

        self._run_in_background(work)

    def _on_detected_mode(self, detected: Any) -> None:
        if self._switching or self._closing:
            return
        if not isinstance(detected, AppMode):
            # Unknown topology -> keep config-based state, but only cover the
            # laptop panel if an external display is known to be present.
            if self._active_mode == AppMode.TEACHER and self.is_hdmi_connected:
                self._apply_active_mode(AppMode.TEACHER)
            return
        if detected == AppMode.EXERCISES and self._parse_mode(self.config.default_mode) == AppMode.TEACHER:
            detected = AppMode.TEACHER  # Teacher is "extend" + curtain
        # Always apply (idempotent) so the curtain starts even when the
        # provisional mode already matched the detected one.
        self._apply_active_mode(detected)

    def _apply_active_mode(self, mode: AppMode) -> None:
        """Makes `mode` the active one (state, curtain, config, tiles)."""
        self._active_mode = mode
        self.monitor.current_mode = mode
        if self.teacher_curtain is not None:
            try:
                if mode == AppMode.TEACHER:
                    if not self.teacher_curtain.is_running():
                        self.teacher_curtain.start()
                else:
                    self.teacher_curtain.stop()
            except Exception as e:
                logger.warning("Curtain update failed: %s", e)
        if self.config.default_mode != mode.value:
            self.config.default_mode = mode.value
            self.config.save()
        self._update_mode_cards_visual(mode)
        self._render_status()

    def _on_mode_restored_threadsafe(self, mode: AppMode) -> None:
        """Called by HdmiMonitor (its thread) after an auto-restore."""
        self._post(lambda: self._on_mode_restored(mode))

    def _on_mode_restored(self, mode: AppMode) -> None:
        """Tk thread: reflects a monitor auto-restore in curtain, config and tiles."""
        if self._closing:
            return
        mode = mode if isinstance(mode, AppMode) else AppMode.NORMAL
        self._apply_active_mode(mode)
        self._show_toast("HDMI desconectado: se restauró el modo Normal", C_WARN, 6000)

    # ------------------------------------------------------------------
    # Visual state
    # ------------------------------------------------------------------
    def _set_tiles_enabled(self, enabled: bool) -> None:
        for card in self.mode_cards.values():
            card["button"].configure(state="normal" if enabled else "disabled")

    def _update_mode_cards_visual(self, active_mode: AppMode | str) -> None:
        """Updates border, fill, badge and button of all mode tiles.

        The active tile's button is never disabled (it can re-apply the mode);
        all buttons are disabled only while a switch is in progress.
        """
        if isinstance(active_mode, str):
            active_mode = self._parse_mode(active_mode)
        self._active_mode = active_mode

        state = "disabled" if self._switching else "normal"
        for mode, card in self.mode_cards.items():
            if mode == active_mode:
                card["frame"].configure(
                    border_width=2, border_color=C_ACCENT, fg_color=C_ACTIVE_FILL
                )
                card["badge"].configure(text="✓ Activo", text_color=C_OK)
                card["button"].configure(
                    text="Reaplicar", state=state, fg_color=C_ACCENT, text_color="#FFFFFF",
                    hover_color=C_ACCENT,
                )
            else:
                card["frame"].configure(border_width=1, border_color=C_BORDER, fg_color=C_CARD)
                card["badge"].configure(text="")
                card["button"].configure(
                    text=card["default_button_text"], state=state, fg_color="transparent",
                    text_color=C_ACCENT, hover_color=C_CARD_HOVER,
                )
        self._refresh_description()

    def _show_toast(self, text: str, color: Any, duration_ms: int) -> None:
        """Shows a non-blocking message in the status bar (0 = until hidden)."""
        if self._toast_after_id is not None:
            try:
                self.after_cancel(self._toast_after_id)
            except Exception:
                pass
            self._toast_after_id = None
        self.toast_label.configure(text=text, text_color=color)
        self.toast_label.grid()
        if duration_ms > 0:
            self._toast_after_id = self.after(duration_ms, self._hide_toast)

    def _hide_toast(self) -> None:
        if self._toast_after_id is not None:
            try:
                self.after_cancel(self._toast_after_id)
            except Exception:
                pass
            self._toast_after_id = None
        try:
            self.toast_label.configure(text="")
            self.toast_label.grid_remove()
        except Exception:
            pass

    def _render_status(self) -> None:
        """Renders the status line: dot + HDMI state + active mode."""
        connected = self._hdmi_connected
        if connected is None:
            connected = bool(self.monitor.last_status)
        mode_name = MODE_INFO[self._active_mode][1]
        if connected:
            text, color = f"● HDMI Conectado · Modo {mode_name}", C_OK
        else:
            text, color = f"○ HDMI Desconectado · Modo {mode_name}", C_WARN
        self.status_pill.configure(text=text, text_color=color)

    # ------------------------------------------------------------------
    # HDMI status
    # ------------------------------------------------------------------
    def _on_hdmi_status_threadsafe(self, connected: bool, names: list[str]) -> None:
        """Callback triggered by HdmiMonitor from its thread; dispatches to the UI thread."""
        self._post(lambda: self._on_hdmi_status_changed(connected, names))

    def _on_hdmi_status_changed(self, connected: bool, names: list[str]) -> None:
        """Handles HDMI status change in the main UI thread."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        if not connected:
            if hasattr(self, "teacher_curtain") and self.teacher_curtain is not None:
                try:
                    self.teacher_curtain.stop()
                except Exception as e:
                    logger.warning("Error stopping teacher curtain on HDMI disconnect: %s", e)

        self._update_hdmi_status_ui(connected, names)

        # In case monitor auto-restored NORMAL mode (not while we are mid-switch,
        # since notify_mode_change pre-sets monitor.current_mode)
        if self.monitor.current_mode is not None and not self._switching:
            self._update_mode_cards_visual(self.monitor.current_mode)
            self._render_status()
            if self.config.default_mode != self.monitor.current_mode.value:
                self.config.default_mode = self.monitor.current_mode.value
                self.config.save()

    def _update_hdmi_status_ui(self, connected: bool, names: list[str]) -> None:
        """Updates the status line and the display names label."""
        self._hdmi_connected = bool(connected)
        self._render_status()

        names_str = ", ".join(names) if names else "Ninguna"
        text = f"Pantallas: {names_str}"
        if len(text) > 64:
            text = text[:61] + "…"
        self.displays_label.configure(text=text)

    def refresh_status(self) -> tuple[bool, list[str]]:
        """Polls HDMI status in the background and updates the UI when done.

        Returns the last known (connected, names) immediately.
        """
        def work() -> None:
            try:
                res = self.monitor.poll_once()
            except Exception as e:
                logger.debug("poll_once failed: %s", e)
                return
            if isinstance(res, tuple) and len(res) == 2:
                connected, names = res
            else:
                connected = bool(self.monitor.last_status)
                names = list(self.monitor.last_display_names or [])
            self._post(lambda: self._update_hdmi_status_ui(bool(connected), list(names)))

        self._run_in_background(work)
        return bool(self.monitor.last_status), list(self.monitor.last_display_names or [])

    def _on_timeout_selected(self, choice: str) -> None:
        """Handles screensaver timeout selection change."""
        seconds = self.TIMEOUT_OPTIONS.get(choice, 60)
        self.config.screensaver_timeout = seconds
        self.config.save()

        if self.monitor.current_mode == AppMode.NORMAL:
            self.display_manager.set_screensaver(active=True, timeout_seconds=seconds)

    def _on_teacher_timeout_selected(self, choice: str) -> None:
        """Handles teacher mode timeout selection change."""
        seconds = self.TEACHER_TIMEOUT_OPTIONS.get(choice, 30)
        self.config.teacher_timeout_seconds = seconds
        self.config.save()

        if hasattr(self, "teacher_curtain") and self.teacher_curtain is not None:
            self.teacher_curtain.timeout_seconds = seconds

    def _on_auto_restore_toggled(self) -> None:
        """Handles auto-restore switch toggle."""
        val = bool(self.auto_restore_var.get())
        self.monitor.auto_restore = val
        self.config.auto_restore_on_disconnect = val
        self.config.save()

    def _on_theme_changed(self, choice: str) -> None:
        """Handles appearance theme change."""
        theme_mode = self.THEME_OPTIONS.get(choice, "dark")
        ctk.set_appearance_mode(theme_mode)
        self.config.theme = theme_mode
        self.config.save()

    def _on_closing(self) -> None:
        """Window close handler: stops curtain, monitor, saves config, and destroys window."""
        self._closing = True
        try:
            if hasattr(self, "teacher_curtain") and self.teacher_curtain is not None:
                self.teacher_curtain.stop()
        except Exception as e:
            logger.warning("Error stopping teacher curtain during close: %s", e)

        try:
            if self.monitor is not None:
                self.monitor.stop()
        except Exception as e:
            logger.warning("Error stopping monitor during close: %s", e)

        try:
            self.config.save()
        except Exception as e:
            logger.warning("Error saving config during close: %s", e)

        self.destroy()

    def destroy(self) -> None:
        """Cancels any pending after timers, stops curtain & monitor, and safely destroys the window."""
        self._closing = True
        try:
            if getattr(self, "_queue_after_id", None) is not None:
                self.after_cancel(self._queue_after_id)
                self._queue_after_id = None
        except Exception:
            pass
        try:
            if hasattr(self, "teacher_curtain") and self.teacher_curtain is not None:
                self.teacher_curtain.stop()
        except Exception as e:
            logger.debug("Error stopping teacher curtain during destroy: %s", e)

        try:
            if hasattr(self, "monitor") and self.monitor is not None and self.monitor.is_running():
                self.monitor.stop()
        except Exception as e:
            logger.debug("Error stopping monitor during destroy: %s", e)

        try:
            if hasattr(self, "tk"):
                for after_id in self.tk.call("after", "info"):
                    try:
                        self.after_cancel(after_id)
                    except Exception:
                        pass
        except Exception:
            pass
        super().destroy()


if __name__ == "__main__":
    app = HdmiSelectorApp()
    app.mainloop()
