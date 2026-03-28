from pathlib import Path
from setters.plugin_api import discover_plugins


def test_discover_plugins_in_repo():
    script_dir = Path(__file__).resolve().parents[1]
    plugins = discover_plugins(script_dir)
    names = [p.name for p in plugins]
    # at least one known plugin should be present in the repository
    assert any(n in names for n in ("swww", "awww", "gnome", "kde"))
