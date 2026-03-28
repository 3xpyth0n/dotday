"""hyprpaper setter plugin

Writes or updates the wallpaper path in ~/.config/hypr/hyprpaper.conf and reloads hyprpaper.
Tries a couple of common config keys and emits a clear error if `hyprctl` fails.
"""

PLUGIN = {
    "name": "hyprpaper",
    "description": "Update hyprpaper config and reload",
    "options": [],
    "check_bins": ["hyprctl"],
}

import subprocess
from pathlib import Path


def _write_cfg_key(cfg_path: Path, key: str, value: str) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    text = ""
    if cfg_path.exists():
        text = cfg_path.read_text()
    lines = [L for L in text.splitlines() if not L.strip().startswith(key + "=")]
    lines.append(f"{key}={value}")
    cfg_path.write_text("\n".join(lines) + "\n")


def apply(image_path: str) -> None:
    cfg_path = Path.home() / ".config" / "hypr" / "hyprpaper.conf"

    # Try updating known keys, try to reload, and surface useful errors.
    tried = []
    for key in ("preload", "wallpaper", "path"):
        try:
            _write_cfg_key(cfg_path, key, image_path)
            subprocess.run(["hyprctl", "hyprpaper", "reload"], check=True)
            return
        except subprocess.CalledProcessError as exc:
            tried.append((key, str(exc)))
            # try next key
            continue

    raise RuntimeError(f"hyprpaper reload failed for keys tried: {tried}")
