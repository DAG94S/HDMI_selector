import json
import os
import tempfile
from HDMI_selector.core.config import AppConfig


def test_config_defaults_and_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.json")
        cfg = AppConfig(config_path=config_path)

        # Check default values for all 5 fields
        assert cfg.screensaver_timeout == 60
        assert cfg.theme == "dark"
        assert cfg.default_mode == "normal"
        assert cfg.poll_interval_seconds == 3
        assert cfg.auto_restore_on_disconnect is True

        # Mutate all 5 fields
        cfg.screensaver_timeout = 120
        cfg.default_mode = "teacher"
        cfg.theme = "light"
        cfg.poll_interval_seconds = 5
        cfg.auto_restore_on_disconnect = False
        cfg.save()

        # Check atomic write cleaned up tmp file
        assert not os.path.exists(f"{config_path}.tmp")
        assert os.path.exists(config_path)

        # Reload and assert all mutated fields persist
        cfg2 = AppConfig(config_path=config_path)
        cfg2.load()
        assert cfg2.screensaver_timeout == 120
        assert cfg2.default_mode == "teacher"
        assert cfg2.theme == "light"
        assert cfg2.poll_interval_seconds == 5
        assert cfg2.auto_restore_on_disconnect is False


def test_config_partial_and_null_values_preserve_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "partial.json")
        partial_data = {
            "screensaver_timeout": 45,
            "default_mode": None,
            "theme": None,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(partial_data, f)

        cfg = AppConfig(config_path=config_path)
        cfg.load()

        assert cfg.screensaver_timeout == 45
        # None values and missing values should preserve defaults
        assert cfg.default_mode == "normal"
        assert cfg.theme == "dark"
        assert cfg.poll_interval_seconds == 3
        assert cfg.auto_restore_on_disconnect is True


def test_config_save_nested_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        nested_dir = os.path.join(tmpdir, "nested", "sub", "dir")
        config_path = os.path.join(nested_dir, "config.json")
        assert not os.path.exists(nested_dir)

        cfg = AppConfig(config_path=config_path, screensaver_timeout=90)
        cfg.save()

        assert os.path.exists(config_path)
        cfg2 = AppConfig(config_path=config_path)
        cfg2.load()
        assert cfg2.screensaver_timeout == 90


def test_config_load_nonexistent_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "nonexistent.json")
        cfg = AppConfig(config_path=config_path)
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


def test_config_load_non_dict_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "list.json")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write('["item1", "item2"]')
        cfg = AppConfig(config_path=config_path)
        cfg.load()
        assert cfg.screensaver_timeout == 60


def test_teacher_timeout_seconds_default_and_persistence(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg = AppConfig(config_path=str(cfg_file))
    assert cfg.teacher_timeout_seconds == 30

    cfg.teacher_timeout_seconds = 15
    cfg.save()

    cfg2 = AppConfig(config_path=str(cfg_file))
    cfg2.load()
    assert cfg2.teacher_timeout_seconds == 15



def _write_config(tmp_path, data):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(data), encoding="utf-8")
    return str(cfg_file)


def test_load_invalid_types_fall_back_per_field(tmp_path):
    path = _write_config(tmp_path, {
        "screensaver_timeout": "120",          # wrong type
        "default_mode": "game",                # unknown mode
        "theme": 5,                            # wrong type
        "poll_interval_seconds": 0,            # out of range
        "auto_restore_on_disconnect": "yes",   # wrong type
        "teacher_timeout_seconds": -3,         # out of range
    })
    cfg = AppConfig(config_path=path)
    cfg.load()

    assert cfg.screensaver_timeout == 60
    assert cfg.default_mode == "normal"
    assert cfg.theme == "dark"
    assert cfg.poll_interval_seconds == 3
    assert cfg.auto_restore_on_disconnect is True
    assert cfg.teacher_timeout_seconds == 30


def test_load_rejects_bools_as_ints_and_huge_values(tmp_path):
    path = _write_config(tmp_path, {
        "screensaver_timeout": True,
        "teacher_timeout_seconds": 10**9,
        "poll_interval_seconds": False,
    })
    cfg = AppConfig(config_path=path)
    cfg.load()
    assert cfg.screensaver_timeout == 60
    assert cfg.teacher_timeout_seconds == 30
    assert cfg.poll_interval_seconds == 3


def test_load_mixed_valid_and_invalid_fields(tmp_path):
    path = _write_config(tmp_path, {
        "screensaver_timeout": 300,
        "default_mode": "PRESENTATION",
        "theme": "light",
        "poll_interval_seconds": 1.5,
        "auto_restore_on_disconnect": False,
        "teacher_timeout_seconds": "abc",
    })
    cfg = AppConfig(config_path=path)
    cfg.load()
    assert cfg.screensaver_timeout == 300
    assert cfg.default_mode == "presentation"
    assert cfg.theme == "light"
    assert cfg.poll_interval_seconds == 1.5
    assert cfg.auto_restore_on_disconnect is False
    assert cfg.teacher_timeout_seconds == 30


def test_load_all_valid_modes(tmp_path):
    for mode in ("presentation", "teacher", "exercises", "normal"):
        path = _write_config(tmp_path, {"default_mode": mode})
        cfg = AppConfig(config_path=path)
        cfg.load()
        assert cfg.default_mode == mode
