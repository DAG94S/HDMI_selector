"""Configuration manager for HDMI Selector application."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".hdmi_selector_config.json")

# Valid values used to validate persisted configuration
VALID_MODES = ("presentation", "teacher", "exercises", "normal")
VALID_THEMES = ("dark", "light", "system")

# Upper bounds (seconds) to reject absurd persisted values
MAX_TIMEOUT_SECONDS = 86400
MAX_POLL_INTERVAL_SECONDS = 3600


def _is_positive_int(value: Any, maximum: int) -> bool:
    """Returns True if value is an int (not bool) within (0, maximum]."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= maximum


def _is_positive_number(value: Any, maximum: float) -> bool:
    """Returns True if value is an int/float (not bool) within (0, maximum]."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < value <= maximum
    )


@dataclass
class AppConfig:
    """Stores application configuration settings and provides load/save persistence.

    Attributes:
        screensaver_timeout: Inactivity timeout in seconds before screensaver activates.
        default_mode: Last applied / default display mode (one of VALID_MODES).
        theme: UI theme ('dark', 'light' or 'system').
        poll_interval_seconds: Polling interval in seconds for device/monitor checks.
        auto_restore_on_disconnect: Whether to restore default display config when HDMI disconnects.
        teacher_timeout_seconds: Inactivity timeout in seconds before dimming screen in teacher mode.
        config_path: Path to the JSON configuration file.
    """

    screensaver_timeout: int = 60
    default_mode: str = "normal"
    theme: str = "dark"
    poll_interval_seconds: int = 3
    auto_restore_on_disconnect: bool = True
    teacher_timeout_seconds: int = 30
    config_path: str = DEFAULT_CONFIG_PATH

    def load(self) -> None:
        """Load configuration from JSON file.

        Each field is validated independently (type and range). Missing, null or
        invalid fields keep their current (default) value, and invalid values are
        logged as warnings. Logs a warning on deserialization or filesystem errors.
        """
        if not os.path.exists(self.config_path):
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to load configuration from %s: %s", self.config_path, e)
            return

        if not isinstance(data, dict):
            logger.warning("Configuration root in %s is not a dictionary", self.config_path)
            return

        validators = {
            "screensaver_timeout": lambda v: _is_positive_int(v, MAX_TIMEOUT_SECONDS),
            "default_mode": lambda v: isinstance(v, str) and v.lower() in VALID_MODES,
            "theme": lambda v: isinstance(v, str) and v.lower() in VALID_THEMES,
            "poll_interval_seconds": lambda v: _is_positive_number(v, MAX_POLL_INTERVAL_SECONDS),
            "auto_restore_on_disconnect": lambda v: isinstance(v, bool),
            "teacher_timeout_seconds": lambda v: _is_positive_int(v, MAX_TIMEOUT_SECONDS),
        }

        for field_name, is_valid in validators.items():
            val = data.get(field_name)
            if val is None:
                continue
            if not is_valid(val):
                logger.warning(
                    "Invalid value %r for '%s' in %s; keeping %r",
                    val,
                    field_name,
                    self.config_path,
                    getattr(self, field_name),
                )
                continue
            if isinstance(val, str):
                val = val.lower()
            setattr(self, field_name, val)

    def save(self) -> None:
        """Save the current configuration to the config file atomically.

        Writes first to a temporary file in the same directory, then atomically
        replaces the destination file to prevent corruption.
        """
        data = {
            "screensaver_timeout": self.screensaver_timeout,
            "default_mode": self.default_mode,
            "theme": self.theme,
            "poll_interval_seconds": self.poll_interval_seconds,
            "auto_restore_on_disconnect": self.auto_restore_on_disconnect,
            "teacher_timeout_seconds": self.teacher_timeout_seconds,
        }
        target_dir = os.path.dirname(os.path.abspath(self.config_path))
        os.makedirs(target_dir, exist_ok=True)
        temp_path = f"{self.config_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.config_path)
