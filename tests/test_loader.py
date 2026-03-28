from pathlib import Path
import pytest
import logging


def test_load_setter_succeeds():
    from dotday import load_setter

    script_dir = Path(__file__).resolve().parents[1]
    mod = load_setter("swww", script_dir)
    assert hasattr(mod, "apply") and callable(mod.apply)


def test_load_setter_rejects_forbidden_import(tmp_path):
    from dotday import load_setter

    script_dir = Path(__file__).resolve().parents[1]
    plugin_path = script_dir / "setters" / "bad_plugin_tmp.py"
    try:
        plugin_path.write_text(
            'PLUGIN = {"name":"bad_plugin_tmp","description":"bad","options":[],"check_bins":[]}\nimport nonexistent_pkg_abc123\n\ndef apply(image_path):\n    return None\n'
        )
        with pytest.raises(RuntimeError):
            load_setter("bad_plugin_tmp", script_dir)
    finally:
        try:
            plugin_path.unlink()
        except Exception as exc:
            logging.debug("test cleanup failed: %s", exc)


def test_load_setter_allows_stdlib_import(tmp_path):
    from dotday import load_setter

    script_dir = Path(__file__).resolve().parents[1]
    plugin_path = script_dir / "setters" / "good_plugin_tmp.py"
    try:
        plugin_path.write_text(
            'PLUGIN = {"name":"good_plugin_tmp","description":"good","options":[],"check_bins":[]}\nimport json\n\ndef apply(image_path):\n    return None\n'
        )
        mod = load_setter("good_plugin_tmp", script_dir)
        assert hasattr(mod, "apply") and callable(mod.apply)
    finally:
        try:
            plugin_path.unlink()
        except Exception:
            pass
