"""illogical-impulse setter plugin

Requirements:
- This setter is for the illogical-impulse desktop environment (end-4/dots-hyprland).
- It requires the script `~/.config/quickshell/ii/scripts/colors/switchwall.sh` to exist and be executable.

Activation:
- Set `plugin = "illogical_impulse"` under the `[setter]` section in `config.toml`.

Behavior:
- Exposes `apply(image_path: str) -> None` which calls the switchwall.sh script with
  the `--image <image_path>` argument. Uses only the Python standard library and
  `subprocess` with `shell=False`.
"""

PLUGIN = {
    "name": "illogical_impulse",
    "description": "Call local switchwall.sh script used by illogical-impulse",
    "options": [],
    "check_bins": [],
}

import os
import subprocess
from pathlib import Path
import logging

try:
    import tomllib
except Exception:
    tomllib = None


SCRIPT_PATH = (
    Path.home()
    / ".config"
    / "quickshell"
    / "ii"
    / "scripts"
    / "colors"
    / "switchwall.sh"
)


def apply(image_path: str) -> None:
    """Apply the wallpaper by calling the illogical-impulse switchwall script.

    Raises RuntimeError with a clear message when the script is missing or when
    the subprocess call fails.
    """
    if not SCRIPT_PATH.exists():
        raise RuntimeError(
            f"illogical-impulse setter: required script not found at {SCRIPT_PATH}"
        )
    if not os.access(SCRIPT_PATH, os.X_OK):
        raise RuntimeError(
            f"illogical-impulse setter: script exists but is not executable: {SCRIPT_PATH}"
        )

    # Determine a color to pass to the switchwall script to avoid interactive prompts.
    color = "#95122c"
    # Attempt to read project config.toml for a configured dot_today color
    config_path = Path(__file__).resolve().parents[1] / "config.toml"
    if tomllib and config_path.exists():
        try:
            with open(config_path, "rb") as f:
                cfg = tomllib.load(f)
            color = cfg.get("colors", {}).get("dot_today", color)
        except Exception as exc:
            logging.debug("illogical_impulse: failed to load config: %s", exc)

    cmd = [str(SCRIPT_PATH), "--image", image_path, "--color", color]

    # Prepare environment: propagate session variables if available so DBus calls work
    env = os.environ.copy()
    for key in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "XDG_RUNTIME_DIR"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    # Run non-interactively: detach stdin to avoid prompts and capture failure
    try:
        subprocess.run(
            cmd,
            check=True,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"illogical-impulse setter: command failed: {exc}") from exc
