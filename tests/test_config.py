import os
import json
import tempfile
from HDMI_selector.core.config import AppConfig

def test_config_defaults_and_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.json")
        cfg = AppConfig(config_path=config_path)
        assert cfg.screensaver_timeout == 60
        assert cfg.theme == "dark"
        assert cfg.default_mode == "normal"
        assert cfg.poll_interval_seconds == 3
        assert cfg.auto_restore_on_disconnect is True
        
        cfg.screensaver_timeout = 120
        cfg.theme = "light"
        cfg.save()
        
        cfg2 = AppConfig(config_path=config_path)
        cfg2.load()
        assert cfg2.screensaver_timeout == 120
        assert cfg2.theme == "light"

def test_config_load_nonexistent_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "nonexistent.json")
        cfg = AppConfig(config_path=config_path)
        # load should not fail or raise exception
        cfg.load()
        assert cfg.screensaver_timeout == 60
        assert cfg.theme == "dark"

def test_config_load_corrupted_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "corrupt.json")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        cfg = AppConfig(config_path=config_path)
        cfg.load()
        assert cfg.screensaver_timeout == 60
