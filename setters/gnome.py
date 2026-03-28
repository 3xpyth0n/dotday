"""gnome setter plugin

Uses gsettings to set the GNOME background picture-uri.
"""

PLUGIN = {
    "name": "gnome",
    "description": "Set GNOME background via gsettings",
    "options": [],
    "check_bins": ["gsettings"],
}

import subprocess


def apply(image_path: str) -> None:
    uri = f"file://{image_path}"
    subprocess.run(
        ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri],
        check=True,
    )
