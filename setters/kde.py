"""kde setter plugin

Calls plasma-apply-wallpaperimage to set a wallpaper on KDE/Plasma.
"""

PLUGIN = {
    "name": "kde",
    "description": "Set wallpaper on KDE using plasma-apply-wallpaperimage",
    "options": [],
    "check_bins": ["plasma-apply-wallpaperimage"],
}

import subprocess


def apply(image_path: str) -> None:
    subprocess.run(["plasma-apply-wallpaperimage", image_path], check=True)
