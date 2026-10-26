"""Main launcher and CLI entry point for HDMI Selector & OLED Saver."""

import argparse
import ctypes
from dataclasses import asdict
import json
import logging
import os
import sys
from typing import Optional

# Permite ejecutar como script directo: `python HDMI_selector/main.py`
# o `python main.py` dentro de la carpeta, además de `-m HDMI_selector.main`.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from HDMI_selector.core.config import AppConfig
from HDMI_selector.core.display_manager import AppMode, DisplayManager
from HDMI_selector.ui.app import HdmiSelectorApp

logger = logging.getLogger("HDMI_selector.main")

TEACHER_CLI_NOTE = (
    "Nota: el telón OLED del Modo Docente solo funciona mientras la interfaz gráfica "
    "(GUI) está abierta. Desde la línea de comandos solo se aplicó la topología "
    "extendida y se pausó el salvapantallas."
)


def enable_dpi_awareness() -> bool:
    """Makes the process DPI aware before any Tk window is created.

    Tries per-monitor DPI awareness (shcore.SetProcessDpiAwareness(2)) and falls back to
    system DPI awareness (user32.SetProcessDPIAware()). No-op on non-Windows platforms.

    Returns:
        True if one of the calls succeeded, False otherwise.
    """
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    try:
        # 0 == S_OK; E_ACCESSDENIED means awareness was already set (still fine).
        res = windll.shcore.SetProcessDpiAwareness(2)
        if res in (0, -2147024891, 0x80070005):
            return True
    except Exception as e:
        logger.debug("SetProcessDpiAwareness unavailable: %s", e)
    try:
        return bool(windll.user32.SetProcessDPIAware())
    except Exception as e:
        logger.debug("SetProcessDPIAware unavailable: %s", e)
    return False


def _persist_default_mode(config: AppConfig, mode: AppMode) -> None:
    """Persists the last applied mode as default_mode (errors are logged, not raised)."""
    try:
        if config.default_mode != mode.value:
            config.default_mode = mode.value
            config.save()
    except Exception as e:
        logger.warning("No se pudo guardar el modo por defecto en la configuración: %s", e)


def build_parser() -> argparse.ArgumentParser:
    """Builds and returns the command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="hdmi-selector",
        description="HDMI Selector & OLED Saver - Gestor de pantallas y protector OLED",
    )
    action_group = parser.add_mutually_exclusive_group(required=False)
    action_group.add_argument(
        "--status",
        action="store_true",
        help="Imprime el estado actual del sistema en formato JSON legible y sale.",
    )
    action_group.add_argument(
        "--mode",
        choices=["presentation", "teacher", "exercises", "normal"],
        type=str.lower,
        help="Conmuta directamente la topología de pantalla y el estado del salvapantallas.",
    )
    action_group.add_argument(
        "--gui",
        action="store_true",
        help="Fuerza el lanzamiento explícito de la interfaz gráfica (GUI).",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Tiempo de inactividad para el salvapantallas en segundos (si aplica).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Formatea la salida de consola estrictamente como JSON puro.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Habilita logging detallado en nivel DEBUG.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Main unified entry point for CLI and GUI modes.

    Args:
        argv: Optional list of command-line arguments. If None, uses sys.argv[1:].

    Returns:
        0 on success (for --mode: the display topology was applied), 1 or argparse
        error code (e.g. 2) on failure.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)

        # Validate dependent modifier flags
        if args.timeout is not None:
            if not args.mode:
                parser.error("El argumento --timeout requiere especificar --mode.")
            if args.timeout <= 0:
                parser.error("El argumento --timeout debe ser un entero positivo mayor que cero.")

        if args.json and not (args.mode or args.status):
            parser.error("El argumento --json requiere especificar --mode o --status.")
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    # Configure logging
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.status:
        try:
            config = AppConfig()
            config.load()
            dm = DisplayManager()
            technologies = dm.get_active_display_technologies()
            status_data = {
                "is_hdmi_connected": dm.is_hdmi_connected(),
                "active_displays": dm.get_active_display_names(technologies),
                "current_topology": dm.get_current_topology(),
                "screensaver": dm.get_screensaver_state(),
                "config": asdict(config),
            }
            print(json.dumps(status_data, indent=2))
            return 0
        except Exception as e:
            logger.error("Error al consultar el estado del sistema: %s", e)
            if args.json:
                print(json.dumps({"success": False, "error": str(e)}), file=sys.stderr)
            else:
                print(f"Error al consultar el estado del sistema: {e}", file=sys.stderr)
            return 1

    if args.mode:
        try:
            app_mode = AppMode(args.mode)
            config = AppConfig()
            config.load()
            dm = DisplayManager()
            kwargs = {}
            if args.timeout is not None:
                kwargs["timeout_seconds"] = args.timeout
            elif app_mode == AppMode.NORMAL:
                kwargs["timeout_seconds"] = config.screensaver_timeout

            result = dm.apply_mode(app_mode, **kwargs)
            topology_ok = bool(result.get("topology_ok", result.get("success")))
            if topology_ok:
                _persist_default_mode(config, app_mode)
                if args.json:
                    if app_mode == AppMode.TEACHER:
                        result = dict(result, note=TEACHER_CLI_NOTE)
                    print(json.dumps(result, indent=2, default=str))
                else:
                    print(f"Modo '{args.mode}' aplicado con éxito.")
                    if result.get("screensaver_ok") is False:
                        print("Advertencia: no se pudo configurar el salvapantallas.")
                    if app_mode == AppMode.TEACHER:
                        print(TEACHER_CLI_NOTE)
                return 0
            else:
                if args.json:
                    print(json.dumps(result, indent=2, default=str), file=sys.stderr)
                else:
                    print(f"Error al aplicar el modo '{args.mode}'.", file=sys.stderr)
                return 1
        except Exception as e:
            logger.error("Error al aplicar el modo '%s': %s", args.mode, e)
            if args.json:
                print(
                    json.dumps({"success": False, "error": str(e)}, indent=2),
                    file=sys.stderr,
                )
            else:
                print(f"Error al aplicar el modo '{args.mode}': {e}", file=sys.stderr)
            return 1

    # Default mode or explicit --gui
    # DPI awareness must be set before any Tk window exists so that Win32 coordinates
    # (cursor, monitor rects) are physical pixels on every monitor.
    enable_dpi_awareness()
    try:
        app = HdmiSelectorApp()
        app.mainloop()
        return 0
    except Exception as e:
        logger.error("Error al iniciar la interfaz gráfica: %s", e)
        print(f"Error al iniciar la aplicación: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
