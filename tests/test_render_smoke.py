import datetime

import copy
import pytest


def test_generate_wallpaper_smoke(tmp_path):
    try:
        from PIL import Image  # type: ignore
    except Exception:
        pytest.skip("Pillow not installed")

    from dotday import generate_wallpaper, DEFAULT_CONFIG

    cfg = copy.deepcopy(DEFAULT_CONFIG)
    out = tmp_path / "wallpaper.png"
    generate_wallpaper(cfg, out, date_override=datetime.date(2026, 2, 14))
    assert out.exists()
    assert out.stat().st_size > 0
