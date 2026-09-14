"""Modern graphical user interface for HDMI Selector & OLED Saver."""

import logging
from tkinter import messagebox
from typing import Any, Optional

import customtkinter as ctk

from HDMI_selector.core.config import AppConfig
from HDMI_selector.core.display_manager import AppMode, DisplayManager
from HDMI_selector.core.hdmi_monitor import HdmiMonitor

logger = logging.getLogger(__name__)


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
        start_monitor: bool = True,
        withdraw: bool = False,
    ) -> None:
        """Initializes the GUI application window and services.

        Args:
            config: Optional AppConfig instance. If None, creates and loads default.
            display_manager: Optional DisplayManager. If None, creates default.
            monitor: Optional HdmiMonitor. If None, creates default.
            start_monitor: If True, starts the background monitor thread.
            withdraw: If True, withdraws window immediately (used in headless/tests).
        """
        super().__init__()

        if withdraw:
            self.withdraw()

        if config is None:
            config = AppConfig()
            config.load()
        self.config = config

        if display_manager is None:
            display_manager = DisplayManager()
        self.display_manager = display_manager

        if monitor is None:
            monitor = HdmiMonitor(
                display_manager=self.display_manager,
                poll_interval=self.config.poll_interval_seconds,
                auto_restore=self.config.auto_restore_on_disconnect,
            )
        self.monitor = monitor
        self.monitor.on_status_change = self._on_hdmi_status_threadsafe

        # Set appearance and styling
        ctk.set_appearance_mode(self.config.theme)
        ctk.set_default_color_theme("blue")

        self.title("🖥️ HDMI Selector & OLED Saver")
        self.geometry("540x660")
        self.minsize(480, 600)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Dictionary tracking card widgets
        self.mode_cards: dict[AppMode, dict[str, Any]] = {}

        # Build UI layout
        self._build_header_and_status()
        self._build_mode_cards()
        self._build_quick_settings_footer()

        # Start background monitor if requested and not yet active
        if start_monitor and not self.monitor.is_running():
            self.monitor.start()

        # Query initial HDMI and displays status
        self.refresh_status()

        # Set initial visual active card state
        initial_mode = (
            self.monitor.current_mode
            if self.monitor.current_mode is not None
            else self._parse_mode(self.config.default_mode)
        )
        self.monitor.current_mode = initial_mode
        self._update_mode_cards_visual(initial_mode)

    @property
    def is_hdmi_connected(self) -> bool:
        """Returns True if HDMI or external display is currently active."""
        if self.monitor.last_status is not None:
            return self.monitor.last_status
        return self.display_manager.is_hdmi_connected()

    @property
    def active_display_names(self) -> list[str]:
        """Returns list of active display names."""
        if self.monitor.last_display_names:
            return self.monitor.last_display_names
        return self.display_manager.get_active_display_names()

    def _parse_mode(self, mode_val: str) -> AppMode:
        """Parses a mode string into an AppMode enum safely."""
        try:
            return AppMode(mode_val)
        except (ValueError, KeyError):
            return AppMode.NORMAL

    def _build_header_and_status(self) -> None:
        """Builds header title and real-time live status pill."""
        self.header_frame = ctk.CTkFrame(self, corner_radius=12)
        self.header_frame.pack(fill="x", padx=16, pady=(16, 8))

        # Title
        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="🖥️ HDMI Selector & OLED Saver",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.title_label.pack(anchor="w", padx=16, pady=(12, 6))

        # Status row container
        status_row = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        status_row.pack(fill="x", padx=16, pady=(0, 8))

        # Live Status Pill
        self.status_pill = ctk.CTkLabel(
            status_row,
            text="○ HDMI Desconectado",
            corner_radius=12,
            fg_color="#E67E22",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            padx=12,
            pady=4,
        )
        self.status_pill.pack(side="left", padx=(0, 10))

        # Refresh manual button
        self.refresh_btn = ctk.CTkButton(
            status_row,
            text="Actualizar",
            width=85,
            height=28,
            font=ctk.CTkFont(size=12),
            command=self.refresh_status,
        )
        self.refresh_btn.pack(side="right")

        # Sublabel with active display names
        self.displays_label = ctk.CTkLabel(
            self.header_frame,
            text="Pantallas: Detectando...",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        )
        self.displays_label.pack(anchor="w", padx=16, pady=(0, 10))

    def _build_mode_cards(self) -> None:
        """Builds the interactive mode selection cards."""
        self.cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.cards_frame.pack(fill="both", expand=True, padx=16, pady=6)

        mode_configs = [
            (
                AppMode.PRESENTATION,
                "Modo Presentación",
                "Pantalla OLED apagada (protección contra quemado). HDMI activo al 100%. Salvapantallas en pausa.",
                "Activar Presentación",
            ),
            (
                AppMode.EXERCISES,
                "Modo Ejercicios",
                "Escritorio extendido para resolver ejercicios con alumnos. Ambas pantallas encendidas. Salvapantallas en pausa.",
                "Activar Ejercicios",
            ),
            (
                AppMode.NORMAL,
                "Modo Normal",
                "Pantalla de laptop únicamente. Salvapantallas activo tras inactividad para proteger el panel OLED.",
                "Restaurar Normal",
            ),
        ]

        for mode, title, desc, btn_text in mode_configs:
            card = ctk.CTkFrame(
                self.cards_frame,
                corner_radius=10,
                border_width=1,
                border_color=("gray75", "gray30"),
            )
            card.pack(fill="x", pady=6, ipady=4)

            # Card Header (Title + Active Badge)
            card_hdr = ctk.CTkFrame(card, fg_color="transparent")
            card_hdr.pack(fill="x", padx=12, pady=(8, 2))

            title_lbl = ctk.CTkLabel(
                card_hdr,
                text=title,
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            title_lbl.pack(side="left")

            badge_lbl = ctk.CTkLabel(
                card_hdr,
                text="",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#10B981",
            )
            badge_lbl.pack(side="right")

            # Card Description
            desc_lbl = ctk.CTkLabel(
                card,
                text=desc,
                font=ctk.CTkFont(size=12),
                wraplength=460,
                justify="left",
                text_color=("gray30", "gray70"),
            )
            desc_lbl.pack(anchor="w", padx=12, pady=4)

            # Action Button
            action_btn = ctk.CTkButton(
                card,
                text=btn_text,
                height=32,
                command=lambda m=mode: self.select_mode(m),
            )
            action_btn.pack(fill="x", padx=12, pady=(4, 8))

            self.mode_cards[mode] = {
                "frame": card,
                "badge": badge_lbl,
                "button": action_btn,
                "default_button_text": btn_text,
            }

    def _build_quick_settings_footer(self) -> None:
        """Builds footer controls for quick configuration settings."""
        self.footer_frame = ctk.CTkFrame(self, corner_radius=12)
        self.footer_frame.pack(fill="x", padx=16, pady=(6, 16))

        footer_title = ctk.CTkLabel(
            self.footer_frame,
            text="⚙️ Configuración Rápida",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        footer_title.pack(anchor="w", padx=14, pady=(10, 4))

        # First row: screensaver timeout dropdown and theme dropdown
        row1 = ctk.CTkFrame(self.footer_frame, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=4)

        # Screensaver Timeout
        lbl_timeout = ctk.CTkLabel(
            row1,
            text="Salvapantallas:",
            font=ctk.CTkFont(size=12),
        )
        lbl_timeout.pack(side="left", padx=(0, 6))

        initial_timeout_choice = self.TIMEOUT_SECONDS_TO_CHOICE.get(
            self.config.screensaver_timeout, "1 min"
        )
        self.timeout_menu = ctk.CTkOptionMenu(
            row1,
            values=list(self.TIMEOUT_OPTIONS.keys()),
            width=100,
            command=self._on_timeout_selected,
        )
        self.timeout_menu.set(initial_timeout_choice)
        self.timeout_menu.pack(side="left", padx=(0, 16))

        # Theme Selector
        lbl_theme = ctk.CTkLabel(
            row1,
            text="Tema:",
            font=ctk.CTkFont(size=12),
        )
        lbl_theme.pack(side="left", padx=(0, 6))

        initial_theme_choice = self.THEME_MAP_REVERSE.get(self.config.theme, "Oscuro")
        self.theme_menu = ctk.CTkOptionMenu(
            row1,
            values=["Oscuro", "Claro"],
            width=100,
            command=self._on_theme_changed,
        )
        self.theme_menu.set(initial_theme_choice)
        self.theme_menu.pack(side="left")

        # Second row: Auto-restore switch
        row2 = ctk.CTkFrame(self.footer_frame, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(4, 12))

        self.auto_restore_var = ctk.BooleanVar(value=self.config.auto_restore_on_disconnect)
        self.auto_restore_switch = ctk.CTkSwitch(
            row2,
            text="Auto-restaurar si se desconecta HDMI",
            font=ctk.CTkFont(size=12),
            variable=self.auto_restore_var,
            command=self._on_auto_restore_toggled,
        )
        self.auto_restore_switch.pack(side="left")

    def select_mode(self, mode: AppMode | str) -> dict:
        """Applies operational mode, updates cards, and persists selection in config.

        Args:
            mode: AppMode enum or string mode name.

        Returns:
            dict: Result from DisplayManager.apply_mode.
        """
        if isinstance(mode, str):
            mode = self._parse_mode(mode)

        # Confirm before activating presentation mode if HDMI is not connected
        if mode == AppMode.PRESENTATION and not self.is_hdmi_connected:
            proceed = messagebox.askyesno(
                "Confirmación HDMI",
                "No se detecta ningún monitor HDMI o pantalla externa conectada.\n\n"
                "Si activa el Modo Presentación, la pantalla de la laptop se apagará.\n"
                "¿Está seguro de que desea continuar?",
            )
            if not proceed:
                return {"success": False, "cancelled": True}

        try:
            res = self.display_manager.apply_mode(
                mode, timeout_seconds=self.config.screensaver_timeout
            )
        except Exception as e:
            logger.error("Error applying mode %s: %s", mode, e)
            messagebox.showerror("Error", f"No se pudo aplicar el modo: {e}")
            return {"success": False, "error": str(e)}

        self.monitor.current_mode = mode
        self._update_mode_cards_visual(mode)
        self.config.default_mode = mode.value
        self.config.save()
        return res

    def _update_mode_cards_visual(self, active_mode: AppMode | str) -> None:
        """Updates the visual border, badge, and button state of all mode cards."""
        if isinstance(active_mode, str):
            active_mode = self._parse_mode(active_mode)

        for mode, card in self.mode_cards.items():
            is_active = mode == active_mode
            if is_active:
                card["frame"].configure(border_width=2, border_color="#3B82F6")
                card["badge"].configure(text="[ACTIVO]", text_color="#10B981")
                card["button"].configure(text="✓ Activo", state="disabled")
            else:
                card["frame"].configure(border_width=1, border_color=("gray75", "gray30"))
                card["badge"].configure(text="")
                card["button"].configure(text=card["default_button_text"], state="normal")

    def _on_hdmi_status_threadsafe(self, connected: bool, names: list[str]) -> None:
        """Callback triggered by HdmiMonitor from background thread; dispatches to UI thread."""
        try:
            self.after(0, lambda: self._on_hdmi_status_changed(connected, names))
        except Exception as e:
            logger.debug("Failed to schedule UI status update: %s", e)

    def _on_hdmi_status_changed(self, connected: bool, names: list[str]) -> None:
        """Handles HDMI status change in the main UI thread."""
        self._update_hdmi_status_ui(connected, names)

        # In case monitor auto-restored NORMAL mode
        if self.monitor.current_mode is not None:
            self._update_mode_cards_visual(self.monitor.current_mode)
            if self.config.default_mode != self.monitor.current_mode.value:
                self.config.default_mode = self.monitor.current_mode.value
                self.config.save()

    def _update_hdmi_status_ui(self, connected: bool, names: list[str]) -> None:
        """Updates the Live Status Pill and display names label."""
        if connected:
            self.status_pill.configure(
                text="● HDMI Conectado",
                fg_color="#2ECC71",
            )
        else:
            self.status_pill.configure(
                text="○ HDMI Desconectado",
                fg_color="#E67E22",
            )

        names_str = ", ".join(names) if names else "Ninguna"
        self.displays_label.configure(text=f"Pantallas: {names_str}")

    def refresh_status(self) -> tuple[bool, list[str]]:
        """Queries HDMI status manually and updates UI."""
        res = self.monitor.poll_once()
        if isinstance(res, tuple) and len(res) == 2:
            connected, names = res
        else:
            connected = bool(self.monitor.last_status)
            names = list(self.monitor.last_display_names or [])

        self._update_hdmi_status_ui(connected, names)
        return connected, names

    def _on_timeout_selected(self, choice: str) -> None:
        """Handles screensaver timeout selection change."""
        seconds = self.TIMEOUT_OPTIONS.get(choice, 60)
        self.config.screensaver_timeout = seconds
        self.config.save()

        if self.monitor.current_mode == AppMode.NORMAL:
            self.display_manager.set_screensaver(active=True, timeout_seconds=seconds)

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
        """Window close handler: stops monitor, saves config, and destroys window."""
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
        """Cancels any pending after timers and safely destroys the window."""
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
