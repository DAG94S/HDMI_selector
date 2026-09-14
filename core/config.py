"""Configuration manager for HDMI Selector application."""

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".hdmi_selector_config.json")


@dataclass
class AppConfig:
    """Stores application configuration settings and provides load/save persistence.

    Attributes:
        screensaver_timeout: Inactivity timeout in seconds before screensaver activates.
        default_mode: Default display mode ('normal' or 'game').
        theme: UI theme ('dark' or 'light').
        poll_interval_seconds: Polling interval in seconds for device/monitor checks.
        auto_restore_on_disconnect: Whether to restore default display config when HDMI disconnects.
        config_path: Path to the JSON configuration file.
    """

    screensaver_timeout: int = 60
    default_mode: str = "normal"
    theme: str = "dark"
    poll_interval_seconds: int = 3
    auto_restore_on_disconnect: bool = True
    config_path: str = DEFAULT_CONFIG_PATH

    def load(self) -> None:
        """Load configuration from JSON file.

        Preserves existing defaults for any missing or null fields.
        Logs a warning on deserialization or filesystem errors.
        """
        if not os.path.exists(self.config_path):
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load configuration from %s: %s", self.config_path, e)
            return

        if not isinstance(data, dict):
            logger.warning("Configuration root in %s is not a dictionary", self.config_path)
            return

        if (val := data.get("screensaver_timeout")) is not None:
            self.screensaver_timeout = val
        if (val := data.get("default_mode")) is not None:
            self.default_mode = val
        if (val := data.get("theme")) is not None:
            self.theme = val
        if (val := data.get("poll_interval_seconds")) is not None:
            self.poll_interval_seconds = val
        if (val := data.get("auto_restore_on_disconnect")) is not None:
            self.auto_restore_on_disconnect = val

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
        }
        target_dir = os.path.dirname(os.path.abspath(self.config_path))
        os.makedirs(target_dir, exist_ok=True)
        temp_path = f"{self.config_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.config_path)
