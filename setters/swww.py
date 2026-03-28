"""swww setter plugin"""

PLUGIN = {
    "name": "swww",
    "description": "Set wallpaper using swww",
    "options": [
        {
            "flags": ["--namespace"],
            "kwargs": {"help": "Wayland namespace", "type": "str"},
        }
    ],
    "check_bins": ["swww"],
}

import os
import subprocess
import time
from setters.plugin_utils import which_bin, is_process_running, start_daemon


def _find_client() -> str | None:
    return which_bin("swww")


def _is_daemon_running() -> bool:
    return is_process_running("swww-daemon")


def apply(image_path: str) -> None:
    client = _find_client()
    if client is None:
        raise RuntimeError("swww not found on PATH; install swww and retry")

    # Try a simple call first (client may auto-select socket)
    try:
        subprocess.run([client, "img", image_path], check=True)
        return
    except subprocess.CalledProcessError:
        pass

    # Ensure daemon is running; try to start it if not
    if not _is_daemon_running():
        started = start_daemon([client, "daemon"], wait_s=0.6)
        if not started:
            raise RuntimeError("failed to start swww daemon")

    # Prefer using detected WAYLAND_DISPLAY namespace if relevant
    ns = os.environ.get("WAYLAND_DISPLAY")
    if ns:
        try:
            subprocess.run(
                [
                    client,
                    "img",
                    "--namespace",
                    ns,
                    image_path,
                    "--transition-type",
                    "fade",
                ],
                check=True,
            )
            return
        except subprocess.CalledProcessError:
            pass

    # Fallback: try with transition and without namespace
    subprocess.run([client, "img", image_path, "--transition-type", "fade"], check=True)
