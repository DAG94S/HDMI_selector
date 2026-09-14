import os
import json
from dataclasses import dataclass

DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".hdmi_selector_config.json")

@dataclass
class AppConfig:
    screensaver_timeout: int = 60
    default_mode: str = "normal"
    theme: str = "dark"
    poll_interval_seconds: int = 3
    auto_restore_on_disconnect: bool = True
    config_path: str = DEFAULT_CONFIG_PATH

    def load(self) -> None:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.screensaver_timeout = data.get("screensaver_timeout", self.screensaver_timeout)
                    self.default_mode = data.get("default_mode", self.default_mode)
                    self.theme = data.get("theme", self.theme)
                    self.poll_interval_seconds = data.get("poll_interval_seconds", self.poll_interval_seconds)
                    self.auto_restore_on_disconnect = data.get("auto_restore_on_disconnect", self.auto_restore_on_disconnect)
            except Exception:
                pass

    def save(self) -> None:
        data = {
            "screensaver_timeout": self.screensaver_timeout,
            "default_mode": self.default_mode,
            "theme": self.theme,
            "poll_interval_seconds": self.poll_interval_seconds,
            "auto_restore_on_disconnect": self.auto_restore_on_disconnect
        }
        os.makedirs(os.path.dirname(os.path.abspath(self.config_path)), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
