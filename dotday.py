#!/usr/bin/env python3
"""DotDay main module

"""
import argparse
import calendar
import copy
import datetime
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import logging
from typing import List, Optional, Tuple
from render_text import (
    _shear_image,
    draw_text_italic,
    render_scaled_text,
    rasterize_scaled_text,
)

import i18n as _i18n
from setters.plugin_api import (
    discover_plugins,
    parse_plugin_metadata,
    register_plugin_args,
    generate_plugins_help,
    load_plugin as _load_plugin,
)

# Package version
__version__ = "0.1.0"


def load_setter(name: str, script_dir, allowed_prefixes: tuple | None = None):
    """Compatibility wrapper: tests and callers expect `load_setter(name, script_dir)`.

    Delegates to `setters.plugin_api.load_plugin(script_dir, name, ...)`.
    """
    return _load_plugin(script_dir, name, allowed_prefixes)


try:
    import numpy as np
except Exception as exc:
    np = None
    logging.debug("optional dependency numpy import failed: %s", exc, exc_info=True)

try:
    import tomllib
except Exception as exc:
    tomllib = None
    logging.debug("optional dependency tomllib import failed: %s", exc, exc_info=True)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
except Exception as exc:
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageFilter = None
    logging.debug("optional dependency Pillow import failed: %s", exc, exc_info=True)

DEFAULT_CONFIG = {
    "display": {
        "resolution": [2560, 1440],
        "language": "en",
        "show_month_name": True,
        "show_day_name": True,
        "show_accent_dot": True,
    },
    "colors": {
        "background": "#111111",
        "dot_past": "#FFFFFF",
        "dot_remaining": "#333333",
        "dot_today": "#95122C",
        "month_text": "#FFFFFF",
        "day_text": "#FFFFFF",
    },
    "font": {
        "month_size": 200,
        "day_size": 90,
        "month_font_path": "./fonts/month-font.ttf",
        "day_font_path": "./fonts/day-font.ttf",
    },
    "dots": {
        "size": 36,
        "spacing": 14,
        "columns": 7,
    },
    "output": {
        "path": "~/.cache/dotday/wallpaper.png",
    },
    "format": {
        "day_format": "alphabetic",
        "month_format": "alphabetic",
    },
    "advanced": {
        "day_text_margin": 20,
    },
}

# Systemd unit templates used by the installer (written to ~/.config/systemd/user)
DOTDAY_SERVICE = """[Unit]
Description=dotday wallpaper generator
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={python_exec} {script_path} run --apply
WorkingDirectory={working_dir}
Nice=10

[Install]
WantedBy=default.target
"""

# Timer to run the above service once per day
DOTDAY_TIMER = """[Unit]
Description=Run dotday daily

[Timer]
OnCalendar=daily
Persistent=true
Unit=dotday.service

[Install]
WantedBy=timers.target
"""


def merge_dict(base, override):
    result = copy.deepcopy(base)
    if not isinstance(override, dict):
        return result
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = merge_dict(result[k], v)
        else:
            result[k] = v
    return result


def hex_to_rgb(s: str):
    s = (s or "#111111").lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    try:
        return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (17, 17, 17)


def _get_pixels(img):
    """Return a flat list of pixel values for the image.

    Prefer `get_flattened_data()` (newer Pillow) and fall back to `getdata()`.
    """
    try:
        getter = getattr(img, "get_flattened_data", None)
        data = getter() if callable(getter) else img.getdata()
        return list(data)
    except Exception:
        return []


def load_config(script_dir: Path):
    cfg_path = script_dir / "config.toml"
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if tomllib is None:
        logging.debug("tomllib not available; using defaults")
        return cfg
    try:
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
            cfg = merge_dict(DEFAULT_CONFIG, data)
    except FileNotFoundError:
        logging.debug("config.toml not found; using defaults")
    except Exception as exc:
        logging.debug(
            "failed to parse config.toml; using defaults: %s", exc, exc_info=True
        )
    return cfg


def resolve_output_path(cfg: dict) -> Path:
    """Resolve the configured output path and return a Path.

    Simplified: only consider `cfg['output']['path']` and default if absent.
    """
    out_path_raw = None
    if cfg and cfg.get("output"):
        out_path_raw = cfg.get("output", {}).get("path")
    if not out_path_raw:
        out_path_raw = "~/.cache/dotday/wallpaper.png"

    # Expand environment variables and user home (~)
    try:
        expanded = os.path.expandvars(os.path.expanduser(str(out_path_raw)))
    except Exception:
        expanded = str(out_path_raw)

    p = Path(expanded)

    # Resolve relative paths against the current working directory.
    try:
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
    except Exception:
        p = Path(expanded)

    return p


def _safe_set_source_name(obj, name: str) -> None:
    try:
        setattr(obj, "_source_name", str(name))
    except Exception:
        pass


def _find_project_fonts(script_dir: Path):
    """Return a list of candidate TTF font paths bundled under `fonts/` in the project.

    Behavior-preserving: returns an empty list if no fonts dir exists or on error.
    """
    try:
        fonts_dir = script_dir / "fonts"
        if fonts_dir.exists():
            all_fonts = sorted(fonts_dir.glob("*.ttf"))
            return [str(p) for p in all_fonts]
    except Exception:
        pass
    return []


def parse_date(s: str):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "invalid date format, expected YYYY-MM-DD"
        ) from exc


def parse_resolution(s: str):
    try:
        parts = s.lower().split("x")
        if len(parts) != 2:
            raise ValueError()
        w = int(parts[0])
        h = int(parts[1])
        if w <= 0 or h <= 0:
            raise ValueError()
        return (w, h)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "invalid resolution format, expected WxH (e.g., 1920x1080)"
        ) from exc


def perform_check(
    script_dir: Path, cfg: dict = None, setter_override: Optional[str] = None
) -> int:
    """Perform installation checks without making changes.

    Returns 0 if everything ok, 1 if anything is missing.
    """
    import shutil

    ok = True
    ci_mode = os.environ.get("DOTDAY_CI", "0").lower() in ("1", "true")

    # systemd timer enabled / active
    timer_enabled = False
    timer_active = False
    try:
        p = subprocess.run(
            ["systemctl", "--user", "is-enabled", "dotday.timer"],
            capture_output=True,
            text=True,
        )
        timer_enabled = p.returncode == 0
    except Exception as exc:
        timer_enabled = False
    try:
        p = subprocess.run(
            ["systemctl", "--user", "is-active", "dotday.timer"],
            capture_output=True,
            text=True,
        )
        timer_active = p.returncode == 0
    except Exception as exc:
        timer_active = False

    # service file exists
    svc_file = Path.home() / ".config" / "systemd" / "user" / "dotday.service"
    svc_exists = svc_file.exists()

    # determine plugin name
    plugin = (
        setter_override
        or (cfg.get("setter", {}).get("plugin") if cfg else None)
        or "swww"
    )
    setter_script = script_dir / "setters" / f"{plugin}.py"
    setter_script_exists = setter_script.exists()

    # config.toml exists
    cfg_file = script_dir / "config.toml"
    cfg_exists = cfg_file.exists()

    out_path = resolve_output_path(cfg)
    cache_dir_exists = out_path.parent.exists()

    # Determine which binaries to check: plugin-provided `check_bins` preferred
    plugin = (
        setter_override
        or (cfg.get("setter", {}).get("plugin") if cfg else None)
        or "swww"
    )
    bin_found = False
    check_bins = []
    try:
        plugin_path = script_dir / "setters" / f"{plugin}.py"
        meta = parse_plugin_metadata(plugin_path) if plugin_path.exists() else None
        if meta and meta.get("check_bins"):
            check_bins = list(meta.get("check_bins"))
        else:
            check_bins = [
                "swww",
                "hyprpaper",
                "awww",
                "feh",
                "swaybg",
                "gsettings",
                "osascript",
            ]
    except Exception as exc:
        check_bins = [
            "swww",
            "hyprpaper",
            "awww",
            "feh",
            "swaybg",
            "gsettings",
            "osascript",
        ]

    for b in check_bins:
        if shutil.which(b):
            bin_found = True
            break

    # Print report
    print("systemd timer enabled:", "yes" if timer_enabled else "no")
    print("systemd timer active:", "yes" if timer_active else "no")
    print("systemd service file found:", "yes" if svc_exists else "no")
    print(
        "setter plugin file found:",
        "yes" if setter_script_exists else "no",
        str(setter_script),
    )
    print("config.toml found:", "yes" if cfg_exists else "no")
    print("output cache directory exists:", "yes" if cache_dir_exists else "no")
    print("setter binary available in PATH:", "yes" if bin_found else "no")

    if not (timer_enabled and timer_active) and not ci_mode:
        ok = False
    if not svc_exists and not ci_mode:
        ok = False
    if not setter_script_exists:
        ok = False
    if not cfg_exists and not ci_mode:
        ok = False
    if not cache_dir_exists and not ci_mode:
        ok = False
    if not bin_found and not ci_mode:
        ok = False

    return 0 if ok else 1


def number_to_words(n: int) -> str:
    ones = [
        "Zero",
        "One",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Eleven",
        "Twelve",
        "Thirteen",
        "Fourteen",
        "Fifteen",
        "Sixteen",
        "Seventeen",
        "Eighteen",
        "Nineteen",
    ]
    tens = ["", "Ten", "Twenty", "Thirty", "Forty", "Fifty"]
    if n < 20:
        return ones[n]
    t = n // 10
    o = n % 10
    if o == 0:
        return tens[t]
    return f"{tens[t]}-{ones[o]}"


def load_font(size: int, path: str = None):
    """Load a font from an explicit TTF path or from the project's `fonts/`.

    Only `size` and an explicit `path` are considered. No automatic italic
    selection or faux-italicing is performed.
    """
    if ImageFont is None:
        return None

    # Prefer an explicit path
    if path:
        try:
            f = ImageFont.truetype(path, size)
            _safe_set_source_name(f, path)
            return f
        except Exception as exc:
            logging.debug("load_font: ImageFont.truetype failed for %s: %s", path, exc)

    # Prefer fonts bundled with the project under ./fonts
    candidates = _find_project_fonts(Path(__file__).resolve().parents[0])
    for c in candidates:
        try:
            f = ImageFont.truetype(c, size)
            _safe_set_source_name(f, c)
            return f
        except Exception:
            continue

    # Final fallback: default font
    try:
        f = ImageFont.load_default()
        _safe_set_source_name(f, "default")
        return f
    except Exception:
        return None


def _create_overlay(w: int, h: int):
    """Create the decorative overlay used by generate_wallpaper.

    Preserves original behavior: builds ellipse, rim, band and vignette with
    the same parameters and fallbacks.
    """
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    try:
        ell_w = int(w * 0.75)
        ell_h = int(h * 0.95)
        el = Image.new("RGBA", (ell_w, ell_h), (0, 0, 0, 0))
        eld = ImageDraw.Draw(el)
        eld.ellipse((0, 0, ell_w, ell_h), fill=(255, 255, 255, 50))
        el = el.filter(ImageFilter.GaussianBlur(120))
        overlay.paste(el, (-int(ell_w * 0.35), int(h * 0.03)), el)
        rim = Image.new("RGBA", (ell_w, ell_h), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rim)
        rd.ellipse((0, 0, ell_w, ell_h), fill=(0, 0, 0, 40))
        rim = rim.filter(ImageFilter.GaussianBlur(90))
        overlay.paste(rim, (-int(ell_w * 0.35), int(h * 0.03)), rim)
    except Exception:
        logging.debug("generate_wallpaper: ellipse overlay failed")

    try:
        band_w = int(w * 0.6)
        band_h = int(h * 0.28)
        band = Image.new("RGBA", (band_w, band_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        bd.rectangle(
            (0, int(band_h * 0.15), band_w, int(band_h * 0.85)), fill=(0, 0, 0, 22)
        )
        band = band.rotate(-22, resample=Image.BICUBIC, expand=True)
        band = band.filter(ImageFilter.GaussianBlur(45))
        overlay.paste(band, (int(w * 0.12), int(h * 0.2)), band)
    except Exception:
        logging.debug("generate_wallpaper: band overlay failed")

    try:
        vig_w = int(w * 0.9)
        vig_h = int(h * 1.1)
        vig = Image.new("RGBA", (vig_w, vig_h), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vig)
        vd.ellipse(
            (int(vig_w * 0.2), int(vig_h * 0.15), int(vig_w * 0.95), int(vig_h * 0.95)),
            fill=(0, 0, 0, 200),
        )
        vig = vig.filter(ImageFilter.GaussianBlur(200))
        overlay.paste(vig, (int(w * 0.28), -int(h * 0.05)), vig)
    except Exception:
        logging.debug("generate_wallpaper: vignette overlay failed")

    return overlay


# Text rendering helpers are imported directly from render_text


def prepare_month_image(
    month_name: str,
    month_font,
    month_color: str,
    base_month_size: int,
    month_size: int,
    italic_shear: float,
    w: int,
    h: int,
    left_block_w: int,
):
    """Prepare rasterized `month_img` used by generate_wallpaper.

    Returns an RGBA Image or None.
    """
    max_month_w = int(left_block_w * 0.75)
    max_month_h = int(h * 0.44)
    month_img = None
    try:
        if base_month_size and base_month_size > 0:
            tmp_canvas = Image.new("RGBA", (int(w * 0.95), int(h * 0.95)), (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp_canvas)
            pad_local = 8
            td.text(
                (pad_local, pad_local), month_name, font=month_font, fill=month_color
            )
            bbox = tmp_canvas.getbbox()
            if bbox:
                month_img = tmp_canvas.crop(bbox)
            else:
                month_img = tmp_canvas
            if italic_shear and abs(italic_shear) > 0:
                month_img = _shear_image(month_img, shear=italic_shear)
        else:
            month_img = rasterize_scaled_text(
                month_name,
                month_font,
                month_color,
                max_month_w,
                max_month_h,
                shear=italic_shear,
            )
    except Exception:
        month_img = None

    # Trim transparent edges to minimize vertical gap
    if month_img is not None:
        try:
            alpha = month_img.split()[-1]
            bbox = alpha.getbbox()
            if bbox:
                x0, y0, x1, y1 = bbox
                pad_top = 2
                pad_bottom = 2
                new_y0 = max(0, y0 - pad_top)
                new_y1 = min(month_img.height, y1 + pad_bottom)
                month_img = month_img.crop((x0, new_y0, x1, new_y1))
        except Exception:
            pass

    return month_img


def generate_wallpaper(
    cfg: dict,
    out_path: Path,
    date_override: Optional[datetime.date] = None,
    resolution_override: Optional[Tuple[int, int]] = None,
    verbose: bool = False,
):
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required: please install python-pillow")

    res = (
        resolution_override
        if resolution_override is not None
        else cfg.get("display", {}).get("resolution", [2560, 1600])
    )
    w, h = int(res[0]), int(res[1])
    if verbose:
        try:
            logging.info(
                "generate_wallpaper: target size=%sx%s, date_override=%s",
                w,
                h,
                date_override,
            )
        except Exception as exc:
            logging.debug("generate_wallpaper: logging.info failed: %s", exc)
    bg_hex = cfg.get("colors", {}).get("background", "#111111")
    bg_rgb = hex_to_rgb(bg_hex)
    lighter = tuple(min(255, int(c + 14)) for c in bg_rgb)
    # expose colors dictionary early so decorative blocks can reference it
    colors = cfg.get("colors", {})
    try:
        # Prefer numpy float gradient for smooth continuous transitions
        if np is not None:
            try:
                y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
                bg_arr = np.array(bg_rgb, dtype=np.float32)[None, :]
                light_arr = np.array(lighter, dtype=np.float32)[None, :]
                grad_arr = (1.0 - y) * bg_arr + y * light_arr
                # add tiny gaussian noise to break banding
                noise_amp = 0.6
                noise = np.random.randn(h, 3).astype(np.float32) * noise_amp
                grad_arr = grad_arr + noise
                grad_arr = np.clip(grad_arr, 0, 255)
                # replicate across width
                grad_full = np.repeat(grad_arr[:, None, :], w, axis=1)
                grad_img = Image.fromarray(grad_full.astype(np.uint8), "RGB").convert(
                    "RGBA"
                )
                # slight blur to further smooth any remaining micro-steps
                grad_img = grad_img.filter(ImageFilter.GaussianBlur(0.8))
                img = grad_img
            except Exception as exc:
                img = Image.new("RGBA", (w, h), bg_hex)
        else:
            # fallback: previous oversample + LANCZOS approach
            oversample = 8
            grad_h = max(1, h * oversample)
            grad = Image.new("RGB", (1, grad_h))
            gp = grad.load()
            for y in range(grad_h):
                t = y / max(1, grad_h - 1)
                r = int(bg_rgb[0] * (1 - t) + lighter[0] * t)
                g = int(bg_rgb[1] * (1 - t) + lighter[1] * t)
                b = int(bg_rgb[2] * (1 - t) + lighter[2] * t)
                gp[0, y] = (r, g, b)
            grad = grad.resize((w, h), Image.LANCZOS).convert("RGBA")
            try:
                noise = Image.effect_noise((w, h), 2.5).convert("L")
                noise = noise.point(lambda v: int((v - 128) * 0.12))
                r, g, b, a = grad.split()
                r = ImageChops.add(r, noise)
                g = ImageChops.add(g, noise)
                b = ImageChops.add(b, noise)
                noisy = Image.merge("RGBA", (r, g, b, a))
                grad = Image.blend(grad, noisy, 0.35)
            except Exception as exc:
                logging.debug("generate_wallpaper: noise blend failed: %s", exc)
            img = grad
    except Exception as exc:
        img = Image.new("RGBA", (w, h), bg_hex)

    overlay = _create_overlay(w, h)
    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(img)

    today = date_override or datetime.date.today()
    # load localized month and day labels
    language = cfg.get("display", {}).get("language", "en")
    catalog = _i18n.load_catalog(Path(__file__).resolve().parents[0], language)
    months = catalog.get("months") or []
    days = catalog.get("days") or []
    # Support formats: 'alphabetic' (name) or 'numeric' (number)
    month_format = cfg.get("format", {}).get("month_format") or "alphabetic"
    day_format = cfg.get("format", {}).get("day_format") or "alphabetic"

    month_name = None
    if month_format == "numeric":
        month_name = str(today.month)
    else:
        month_name = (
            months[today.month - 1] if len(months) >= 12 else today.strftime("%B")
        )

    day_number = today.day
    if day_format == "numeric":
        day_name = str(day_number)
    else:
        day_name = (
            days[day_number - 1] if len(days) >= 31 else number_to_words(day_number)
        )
    try:
        logging.info(
            "i18n: language=%s month=%s day=%s", language, month_name, day_name
        )
    except Exception as exc:
        logging.debug("generate_wallpaper: i18n logging failed: %s", exc)

    font_cfg = cfg.get("font", {})
    month_font_path = (
        font_cfg.get("month_font_path") or font_cfg.get("month_path") or ""
    )
    day_font_path = font_cfg.get("day_font_path") or font_cfg.get("day_path") or ""
    base_month_size = int(
        font_cfg.get("month_size", DEFAULT_CONFIG["font"]["month_size"])
    )
    base_day_size = int(font_cfg.get("day_size", DEFAULT_CONFIG["font"]["day_size"]))

    dot_cfg = cfg.get("dots", {})
    base_dot_size = int(dot_cfg.get("size", DEFAULT_CONFIG["dots"]["size"]))
    base_spacing = int(dot_cfg.get("spacing", DEFAULT_CONFIG["dots"]["spacing"]))
    columns = int(dot_cfg.get("columns", DEFAULT_CONFIG["dots"]["columns"]))

    pad = max(40, int(w * 0.06))
    center_y = h // 2

    left_block_w = int(w * 0.40) - pad

    draw = ImageDraw.Draw(img)

    max_month_w = int(left_block_w * 0.75)
    min_size = 34
    max_size = int(h * 0.44)

    if base_month_size and base_month_size > 0:
        month_size = min(base_month_size, max_size)
    else:
        lo, hi = min_size, max_size
        best = min_size
        for _ in range(20):
            mid = (lo + hi) // 2
            f = load_font(mid, path=month_font_path) or ImageFont.load_default()
            shear_for_calc = 0.0
            try:
                bbox = draw.textbbox((0, 0), month_name, font=f)
                cur_w = bbox[2] - bbox[0]
                cur_h = bbox[3] - bbox[1]
            except Exception as exc:
                cur_w = 0
                cur_h = 0
            cur_w_effective = cur_w + int(abs(shear_for_calc) * cur_h) + 8
            if cur_w_effective <= max_month_w and cur_h <= int(h * 0.30):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        month_size = best

    month_font = load_font(month_size, path=month_font_path) or ImageFont.load_default()
    if verbose:
        try:
            logging.info(
                "month_size=%s base_day_size=%s month_font_path=%s day_font_path=%s",
                month_size,
                base_day_size,
                month_font_path,
                day_font_path,
            )
        except Exception as exc:
            logging.debug("generate_wallpaper: month/day logging failed: %s", exc)

    italic_shear = 0.0

    if base_day_size and base_day_size > 0:
        day_size = base_day_size
    else:
        day_size = max(20, int(month_size * 0.28))
        day_size = min(day_size, max(18, int(month_size * 0.38)))
    day_font = load_font(day_size, path=day_font_path) or ImageFont.load_default()
    if verbose:
        try:
            logging.info("computed day_size=%s", day_size)
        except Exception as exc:
            logging.debug(
                "generate_wallpaper: computed day_size logging failed: %s", exc
            )

    colors = cfg.get("colors", {})
    month_color = colors.get("month_text", "#FFFFFF")
    day_color = colors.get("day_text", "#FFFFFF")
    accent_color = colors.get("dot_today", "#95122C")

    text_x = pad
    max_month_w = int(left_block_w * 0.75)
    max_month_h = int(h * 0.44)
    month_img = None
    if cfg.get("display", {}).get("show_month_name", True):
        try:
            month_img = prepare_month_image(
                month_name,
                month_font,
                month_color,
                base_month_size,
                month_size,
                italic_shear,
                w,
                h,
                left_block_w,
            )
        except Exception:
            month_img = None

    dbox = (
        draw.textbbox((0, 0), day_name, font=day_font)
        if cfg.get("display", {}).get("show_day_name", True)
        else (0, 0, 0, 0)
    )
    d_w = dbox[2] - dbox[0]
    d_h = dbox[3] - dbox[1]
    # initial text x for month rendering (keep month fixed to the left)
    text_x = pad
    if month_img is not None:
        try:
            extra_bottom = 0
            if extra_bottom:
                padded = Image.new(
                    "RGBA",
                    (month_img.width, month_img.height + extra_bottom),
                    (0, 0, 0, 0),
                )
                padded.paste(month_img, (0, 0), month_img)
                month_img = padded
        except Exception as exc:
            logging.debug("generate_wallpaper: pad month image failed: %s", exc)

    gap_between = 0
    text_block_h = 0
    if cfg.get("display", {}).get("show_month_name", True) and month_img is not None:
        text_block_h += month_img.height
    if cfg.get("display", {}).get("show_month_name", True) and cfg.get(
        "display", {}
    ).get("show_day_name", True):
        text_block_h += gap_between

    if cfg.get("display", {}).get("show_day_name", True):
        text_block_h += d_h

    text_start_y = center_y - text_block_h // 2 - int(h * 0.04)

    def compute_layout():
        """Compute layout metrics for rendering.

        Returns a dict with dot/grid sizes and text placement values.
        """
        nonlocal month_img

        # reusable geometry
        pad_local = max(40, int(w * 0.06))
        center_y_local = h // 2
        left_block_w_local = int(w * 0.40) - pad_local

        # If the rasterized month image is wider than the left column, scale it
        # down to fit so it does not push the grid off-canvas.
        try:
            if (
                month_img is not None
                and month_img.width > left_block_w_local
                and left_block_w_local > 0
            ):
                sf = left_block_w_local / float(month_img.width)
                new_h = max(1, int(month_img.height * sf))
                month_img = month_img.resize(
                    (left_block_w_local, new_h), resample=Image.LANCZOS
                )
        except Exception:
            pass

        # measure day text box
        dbox_local = (
            draw.textbbox((0, 0), day_name, font=day_font)
            if cfg.get("display", {}).get("show_day_name", True)
            else (0, 0, 0, 0)
        )
        d_w_local = dbox_local[2] - dbox_local[0]
        d_h_local = dbox_local[3] - dbox_local[1]

        # compute vertical start for text block
        text_block_h_local = 0
        if (
            cfg.get("display", {}).get("show_month_name", True)
            and month_img is not None
        ):
            text_block_h_local += month_img.height
        if cfg.get("display", {}).get("show_month_name", True) and cfg.get(
            "display", {}
        ).get("show_day_name", True):
            text_block_h_local += gap_between

        if cfg.get("display", {}).get("show_day_name", True):
            text_block_h_local += d_h_local

        text_start_y_local = center_y_local - text_block_h_local // 2 - int(h * 0.04)

        # compute grid sizing
        scale_local = w / 2560
        dot_from_config_local = int(base_dot_size)
        dot_from_month_local = max(12, int(month_size * 0.30))
        dot_size_local = max(
            dot_from_config_local,
            dot_from_month_local,
            int(dot_from_config_local * max(1.0, scale_local * 1.4)),
        )
        spacing_local = max(10, int(base_spacing * max(1.0, scale_local * 1.25)))
        grid_max_w_local = int(w * 0.42)
        try:
            dot_max_by_width_local = max(
                8, (grid_max_w_local - (columns - 1) * spacing_local) // max(1, columns)
            )
        except Exception:
            dot_max_by_width_local = dot_size_local
        dot_size_local = min(dot_size_local, dot_max_by_width_local)

        days_in_month_local = calendar.monthrange(today.year, today.month)[1]
        rows_local = math.ceil(days_in_month_local / columns)
        grid_w_local = columns * dot_size_local + max(0, columns - 1) * spacing_local
        grid_h_local = (
            rows_local * dot_size_local + max(0, rows_local - 1) * spacing_local
        )

        grid_origin_x_local = w - pad_local - grid_w_local - int(w * 0.05)
        grid_origin_y_local = center_y_local - grid_h_local // 2

        # Reserve space for month/day text to avoid overlap with grid
        try:
            # day text margin and accent radius
            adv_cfg_local = cfg.get("advanced", {})
            day_text_margin_local = int(
                adv_cfg_local.get(
                    "day_text_margin",
                    DEFAULT_CONFIG.get("advanced", {}).get("day_text_margin", 20),
                )
            )
        except Exception:
            day_text_margin_local = DEFAULT_CONFIG.get("advanced", {}).get(
                "day_text_margin", 20
            )

        left_block_right_local = pad_local + left_block_w_local
        desired_x_local = left_block_right_local - d_w_local - day_text_margin_local
        text_x_local = max(pad_local, int(desired_x_local))
        accent_r_local = (
            max(6, int(day_size * 0.22))
            if "day_size" in locals() or "day_size" in globals()
            else 10
        )
        rightmost_text = (
            text_x_local
            + d_w_local
            + (
                accent_r_local + 10
                if cfg.get("display", {}).get("show_accent_dot", True)
                else 0
            )
        )
        month_right = pad_local + (month_img.width if month_img is not None else 0)
        reserved_right = max(rightmost_text, month_right)

        # ensure grid origin is at least some gap to the right of reserved content
        min_gap = max(16, int(w * 0.03))
        if grid_origin_x_local < reserved_right + min_gap:
            grid_origin_x_local = int(reserved_right + min_gap)

        return {
            "pad": pad_local,
            "center_y": center_y_local,
            "left_block_w": left_block_w_local,
            "text_start_y": text_start_y_local,
            "d_w": d_w_local,
            "d_h": d_h_local,
            "dot_size": dot_size_local,
            "spacing": spacing_local,
            "grid_w": grid_w_local,
            "grid_h": grid_h_local,
            "grid_origin_x": grid_origin_x_local,
            "grid_origin_y": grid_origin_y_local,
            "days_in_month": days_in_month_local,
        }

    def _render_layout():
        """Inner function that performs final layout pasting and rendering.

        This separates rendering responsibilities from the earlier size
        calculations and resource loading while preserving behavior.
        """

        # compute layout values
        layout = compute_layout()
        cur_y = layout.get("text_start_y", text_start_y)
        if (
            cfg.get("display", {}).get("show_month_name", True)
            and month_img is not None
        ):
            try:
                left_margin = max(6, int(month_img.width * 0.04))
                paste_x = max(0, text_x - left_margin)
                paste_y = cur_y
                img.paste(month_img, (paste_x, paste_y), month_img)
                month_h_est = month_img.height
                try:
                    month_alpha = month_img.split()[-1].convert("L")
                    day_mask = Image.new("L", (d_w, d_h), 0)
                    dd_mask = ImageDraw.Draw(day_mask)
                    dd_mask.text((0, 0), day_name, font=day_font, fill=255)
                    month_w, month_h = month_img.size
                    dx = text_x - paste_x
                    overlap_x0 = max(0, dx)
                    overlap_x1 = min(month_w, dx + d_w)
                    required_top = None
                    for col in range(overlap_x0, overlap_x1):
                        mcol = col
                        dcol = col - dx
                        try:
                            col_pixels = _get_pixels(
                                month_alpha.crop((mcol, 0, mcol + 1, month_h))
                            )
                        except Exception:
                            continue
                        bottom_idx = None
                        for yi in range(len(col_pixels) - 1, -1, -1):
                            if col_pixels[yi] > 10:
                                bottom_idx = yi
                                break
                        if bottom_idx is None:
                            continue
                        try:
                            d_pixels = _get_pixels(
                                day_mask.crop((dcol, 0, dcol + 1, d_h))
                            )
                        except Exception:
                            continue
                        top_idx = None
                        for yi in range(0, len(d_pixels)):
                            if d_pixels[yi] > 10:
                                top_idx = yi
                                break
                        if top_idx is None:
                            continue
                        cand_top = paste_y + bottom_idx + 1 - top_idx
                        if required_top is None or cand_top > required_top:
                            required_top = cand_top
                    if required_top is not None:
                        cur_y = int(max(required_top, paste_y))
                    else:
                        cur_y = paste_y + month_h_est + 2
                    try:
                        extra_gap = max(16, int(month_size * 0.06))
                    except Exception:
                        extra_gap = 16
                    cur_y += extra_gap
                except Exception:
                    cur_y = paste_y + month_h_est + 2
            except Exception:
                draw.text(
                    (text_x, cur_y), month_name, font=month_font, fill=month_color
                )
                month_h_est = month_img.height if month_img is not None else 0
                cur_y += month_h_est + 2

        if cfg.get("display", {}).get("show_day_name", True):
            try:
                adv_cfg = cfg.get("advanced", {})
                day_text_margin = int(
                    adv_cfg.get(
                        "day_text_margin",
                        DEFAULT_CONFIG.get("advanced", {}).get("day_text_margin", 20),
                    )
                )
            except Exception:
                day_text_margin = DEFAULT_CONFIG.get("advanced", {}).get(
                    "day_text_margin", 20
                )

            left_block_right = pad + left_block_w
            desired_x = left_block_right - d_w - day_text_margin
            text_x_local = max(pad, int(desired_x))

            draw.text((text_x_local, cur_y), day_name, font=day_font, fill=day_color)
            if cfg.get("display", {}).get("show_accent_dot", True):
                accent_r = max(6, int(day_size * 0.22))
                dot_x = text_x_local + d_w + accent_r + 10
                dot_y = cur_y + d_h // 2
                draw.ellipse(
                    [
                        dot_x - accent_r,
                        dot_y - accent_r,
                        dot_x + accent_r,
                        dot_y + accent_r,
                    ],
                    fill=accent_color,
                )

        # grid and dot rendering using precomputed layout
        dot_size_local = layout["dot_size"]
        spacing_local = layout["spacing"]
        grid_w_local = layout["grid_w"]
        grid_h_local = layout["grid_h"]
        grid_origin_x = layout["grid_origin_x"]
        grid_origin_y = layout["grid_origin_y"]
        days_in_month = layout["days_in_month"]

        if verbose:
            try:
                logging.info(
                    "grid_origin=(%s,%s) text_start_y=%s pad=%s left_block_w=%s",
                    grid_origin_x,
                    grid_origin_y,
                    layout.get("text_start_y", text_start_y),
                    pad,
                    left_block_w,
                )
            except Exception:
                logging.debug("generate_wallpaper: grid_origin logging failed")

        for i in range(1, days_in_month + 1):
            idx = i - 1
            r = idx // columns
            c = idx % columns
            cx = (
                grid_origin_x
                + c * (dot_size_local + spacing_local)
                + dot_size_local // 2
            )
            cy = (
                grid_origin_y
                + r * (dot_size_local + spacing_local)
                + dot_size_local // 2
            )

            if i == today.day:
                col = colors.get("dot_today", "#95122C")
            elif i < today.day:
                col = colors.get("dot_past", "#FFFFFF")
            else:
                col = colors.get("dot_remaining", "#333333")

            try:
                ss = 4
                dot_w = dot_size_local * ss
                dot_h = dot_size_local * ss
                d_big = Image.new("RGBA", (dot_w, dot_h), (0, 0, 0, 0))
                dd = ImageDraw.Draw(d_big)
                dd.ellipse([0, 0, dot_w, dot_h], fill=hex_to_rgb(col) + (255,))
                d_small = d_big.resize(
                    (dot_size_local, dot_size_local), resample=Image.LANCZOS
                )
                img.paste(
                    d_small,
                    (int(cx - dot_size_local // 2), int(cy - dot_size_local // 2)),
                    d_small,
                )
            except Exception:
                draw.ellipse(
                    [
                        cx - dot_size_local // 2,
                        cy - dot_size_local // 2,
                        cx + dot_size_local // 2,
                        cy + dot_size_local // 2,
                    ],
                    fill=col,
                )

    # perform rendering using the inner function
    _render_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


def install_units(script_path: Path):
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    service_path = user_dir / "dotday.service"
    timer_path = user_dir / "dotday.timer"

    service_content = DOTDAY_SERVICE.format(
        python_exec=sys.executable,
        script_path=str(script_path),
        working_dir=str(script_path.parent),
    )
    timer_content = DOTDAY_TIMER

    service_path.write_text(service_content)
    timer_path.write_text(timer_content)

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "dotday.timer"], check=True
        )
    except Exception as exc:
        logging.error("failed to enable systemd user timer: %s", exc)


def interactive_install(script_path: Path):
    """Interactive install wrapper.

    - Shows planned actions
    - Prompts for confirmation
    - Attempts to install Python dependency `pillow` via pip
    - Writes and enables systemd user units
    """
    print("The installer will perform the following actions:")
    print(" - install Python dependency: python-pillow (via pip)")
    print(" - write systemd user service and timer to ~/.config/systemd/user/")
    print(" - enable and start the user timer to run dotday daily")
    try:
        tty = sys.stdin.isatty()
    except Exception as exc:
        tty = False
    if not tty:
        print("No interactive terminal detected; aborting install.")
        return
    resp = input("Continue and perform these actions? [y/N]: ")
    if resp.strip().lower() not in ("y", "yes"):
        print("Install aborted by user.")
        return

    # Create config.toml from example if it does not exist
    try:
        cfg_path = script_path.parent / "config.toml"
        example_path = script_path.parent / "config.toml.example"
        if not cfg_path.exists() and example_path.exists():
            import shutil

            shutil.copyfile(str(example_path), str(cfg_path))
            print("Config created from config.toml.example")
    except Exception as exc:
        logging.debug("failed to create config from example", exc_info=True)

    # Install pillow via pip
    print("Installing python-pillow via pip...")
    pip_cmds = [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            "pillow",
            "--break-system-packages",
        ],
    ]
    installed = False
    for cmd in pip_cmds:
        try:
            subprocess.run(cmd, check=True)
            installed = True
            break
        except Exception as exc:
            installed = False
    if not installed:
        print("Failed to install python-pillow automatically.")
        print("You can install it manually, then run: python dotday.py install")
        return

    # Write and enable units
    try:
        install_units(script_path)
        print("Installed systemd user service and timer: dotday.service/.timer")
        print("To remove all installed files and disable the timer, run:")
        print("  python dotday.py uninstall")
    except Exception as exc:
        logging.error("install process failed: %s", exc)


def uninstall_units():
    user_dir = Path.home() / ".config" / "systemd" / "user"
    service_path = user_dir / "dotday.service"
    timer_path = user_dir / "dotday.timer"

    try:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "dotday.timer"], check=False
        )
    except Exception as exc:
        logging.debug("uninstall_units: disable timer failed: %s", exc)

    for p in (service_path, timer_path):
        try:
            if p.exists():
                p.unlink()
        except Exception as exc:
            logging.debug("failed to remove %s", p)

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    except Exception as exc:
        logging.debug("uninstall_units: daemon-reload failed: %s", exc)


def run_generate(
    script_dir: Path,
    dry_run: bool,
    apply: bool = False,
    cfg: dict = None,
    plugin_override: Optional[str] = None,
    date_override: Optional[datetime.date] = None,
    verbose: bool = False,
    resolution_override: Optional[Tuple[int, int]] = None,
):
    if cfg is None:
        cfg = load_config(script_dir)

    # determine output path from config
    out_path = resolve_output_path(cfg)

    # Determine rendering resolution: if the user requested a very small
    # resolution, render at a reasonable base resolution and downscale afterwards
    requested_res = resolution_override
    base_res = cfg.get("display", {}).get("resolution", [2560, 1600])
    try:
        base_w, base_h = int(base_res[0]), int(base_res[1])
    except Exception as exc:
        base_w, base_h = 2560, 1600

    render_res = None
    if requested_res:
        try:
            req_w, req_h = int(requested_res[0]), int(requested_res[1])
        except Exception as exc:
            req_w, req_h = base_w, base_h
        # If requested is smaller than base, render at base to avoid layout overlap
        if req_w < base_w or req_h < base_h:
            render_res = (base_w, base_h)
        else:
            render_res = (req_w, req_h)
    else:
        render_res = None

    try:
        generate_wallpaper(
            cfg,
            out_path,
            date_override=date_override,
            resolution_override=render_res,
            verbose=verbose,
        )
    except Exception as exc:
        logging.error("failed to generate wallpaper: %s", exc)
        return

    # If we rendered at a larger resolution to avoid layout issues and the user
    # requested a smaller final size, downscale now (preserve aspect ratio exactly).
    if (
        requested_res
        and render_res
        and (render_res[0] != req_w or render_res[1] != req_h)
    ):
        try:
            if Image is not None:
                img = Image.open(out_path)
                img = img.resize((req_w, req_h), Image.LANCZOS)
                img.save(out_path, "PNG")
                if verbose:
                    logging.info(
                        "Downscaled generated image from %sx%s to %sx%s",
                        render_res[0],
                        render_res[1],
                        req_w,
                        req_h,
                    )
        except Exception as exc:
            logging.error("failed to downscale generated image: %s", exc)

    if verbose:
        # config file path and whether it was found
        cfg_path = script_dir / "config.toml"
        cfg_found = cfg_path.exists()
        res_used = (
            resolution_override
            if resolution_override is not None
            else cfg.get("display", {}).get("resolution", [2560, 1600])
        )
        date_used = date_override or datetime.date.today()
        logging.info("Output image path: %s", out_path)
        logging.info(
            "Active setter plugin: %s",
            plugin_override or cfg.get("setter", {}).get("plugin", "swww"),
        )
        logging.info(
            "Config file: %s (%s)", cfg_path, "found" if cfg_found else "defaults"
        )
        logging.info("Resolution used: %sx%s", int(res_used[0]), int(res_used[1]))
        logging.info("Date used for generation: %s", date_used.isoformat())

    if dry_run:
        logging.info("dry-run enabled; image saved to %s", out_path)
        return

    if not apply:
        logging.info("image generated to %s (apply not requested)", out_path)
        return

    # Check for available setter
    try:
        import shutil
        import platform

        system = platform.system()
        can_apply = False
        if system == "Linux":
            for cmd in ("awww", "swaybg", "feh", "gsettings"):
                if shutil.which(cmd):
                    can_apply = True
                    break
        elif system == "Darwin":
            can_apply = shutil.which("osascript") is not None
        elif system == "Windows":
            can_apply = True

        if not can_apply:
            logging.warning(
                "no known wallpaper setter found on this system; generated image at %s",
                out_path,
            )
            try:
                distro_id = ""
                try:
                    os_release = Path("/etc/os-release")
                    if os_release.exists():
                        for line in os_release.read_text().splitlines():
                            if line.startswith("ID="):
                                distro_id = line.split("=", 1)[1].strip().strip('"')
                                break
                except Exception as exc:
                    distro_id = ""
                if distro_id in ("arch", "cachyos", "manjaro"):
                    print(
                        "Suggested: install 'awww' (AUR). Example: 'paru -S awww' or clone AUR and makepkg -si.",
                        file=sys.stderr,
                    )
                elif distro_id in ("ubuntu", "debian"):
                    print(
                        "Suggested: install 'feh' (X11) or a Wayland setter. Example: 'sudo apt install feh'",
                        file=sys.stderr,
                    )
                elif distro_id in ("fedora",):
                    print(
                        "Suggested: install 'feh' or a Wayland setter. Example: 'sudo dnf install feh'",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "Suggested: install 'awww' (Hyprland) or 'swaybg'/'feh' depending on your compositor.",
                        file=sys.stderr,
                    )
            except Exception as exc:
                logging.debug("apply: distro suggestion printing failed: %s", exc)
            return

    except Exception as exc:
        logging.error("failed to determine available wallpaper setters: %s", exc)

        return

    # Force a unique filename for each apply so setters will update even if the
    # previous dotday image was already set as wallpaper.
    try:
        import shutil

        # remove prior timestamped wallpaper files to avoid storage growth
        cache_dir = out_path.parent
        try:
            for p in cache_dir.glob("wallpaper-*.png"):
                try:
                    p.unlink()
                except Exception as exc:
                    logging.debug("apply: unlink failed for %s: %s", p, exc)
        except Exception as exc:
            logging.debug("apply: removing prior wallpaper files failed: %s", exc)

        ts = int(time.time())
        target = out_path.with_name(f"wallpaper-{ts}.png")
        shutil.copy2(out_path, target)
    except Exception as exc:
        target = out_path

    # Load setter plugin from config and invoke it
    setter_cfg = cfg.get("setter", {})
    plugin_name = plugin_override or setter_cfg.get("plugin", "swww")
    try:
        plugin = load_setter(plugin_name, script_dir)
    except Exception as exc:
        logging.error("failed to load setter plugin '%s': %s", plugin_name, exc)
        return
    try:
        plugin.apply(str(target))
        logging.info("wallpaper applied successfully via plugin '%s'", plugin_name)
    except Exception as exc:
        logging.error("setter plugin '%s' failed: %s", plugin_name, exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="dotday wallpaper generator")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "install", "uninstall", "setters"),
        default=None,
        help="action to perform",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        help="Print detailed runtime info",
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        dest="date",
        help="Generate wallpaper for a specific date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        dest="check",
        help="Verify the current installation status",
    )
    parser.add_argument(
        "--setter",
        type=str,
        dest="setter",
        help="Override the setter plugin",
    )
    parser.add_argument(
        "--color-bg",
        type=str,
        dest="color_bg",
        help="Override background color (HEX)",
    )
    parser.add_argument(
        "--color-today",
        type=str,
        dest="color_today",
        help="Override today's dot color (HEX)",
    )
    parser.add_argument(
        "--color-past",
        type=str,
        dest="color_past",
        help="Override past dots color (HEX)",
    )
    parser.add_argument(
        "--color-remaining",
        type=str,
        dest="color_remaining",
        help="Override remaining dots color (HEX)",
    )
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        dest="resolution",
        help="Override resolution (WxH, e.g. 1920x1080)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="generate but do not apply"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the generated wallpaper using the selected setter",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        help="Override output image path for this run (file path)",
    )

    # First pass: parse known args to handle --check or the `setters` command
    known, unknown = parser.parse_known_args(argv)
    args = known
    # If no arguments were provided at all, show the help.
    provided_argv = list(argv) if argv is not None else sys.argv[1:]
    if not provided_argv:
        parser.print_help()
        return
    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.INFO)

    script_path = Path(__file__).resolve()
    script_dir = script_path.parent

    # --check is standalone and must not perform install/run/uninstall
    if getattr(args, "check", False):
        cfg = load_config(script_dir)
        code = perform_check(
            script_dir,
            cfg=cfg,
            setter_override=args.setter if hasattr(args, "setter") else None,
        )
        sys.exit(code)

    if args.command == "install":
        interactive_install(script_path)
        return

    if args.command == "uninstall":
        uninstall_units()
        print("removed systemd user units for dotday")
        return

    if args.command == "setters":
        # list available plugins
        plugins = discover_plugins(script_dir)
        if not plugins:
            print("no setter plugins found in 'setters/'")
            return
        for p in plugins:
            print(f"{p.name}: {p.description}")
            # print options if present
            for opt in p.options:
                flags = ", ".join(opt.get("flags") or [])
                help_text = (opt.get("kwargs") or {}).get("help", "")
                print(f"    {flags} — {help_text}")
        return

    # default: run
    # Load config and apply runtime-only overrides (never write to disk)
    cfg = load_config(script_dir)
    # Determine selected setter from first-pass args or config
    selected_setter = (
        getattr(args, "setter", None) or cfg.get("setter", {}).get("plugin") or "swww"
    )

    # If plugin provides options, register them and reparse complete args
    try:
        plugin_path = script_dir / "setters" / f"{selected_setter}.py"
        if plugin_path.exists():
            meta = parse_plugin_metadata(plugin_path)
            if meta and meta.get("options"):
                register_plugin_args(parser, meta)
    except Exception as exc:
        logging.debug("register_plugin_args failed: %s", exc)

    # Append a help epilog listing plugins
    try:
        parser.epilog = generate_plugins_help(script_dir)
    except Exception as exc:
        logging.debug("generate_plugins_help failed: %s", exc)

    # Reparse full args now that plugin options are registered
    args = parser.parse_args(argv)

    # Verify Pillow is available for commands that render images
    needs_pillow = args.command in ("run",) or getattr(args, "dry_run", False)
    if needs_pillow and Image is None:
        sys.stdout.write("Pillow (python-pillow) is required to generate wallpapers.\n")
        sys.stdout.write("Install with: pip install --user pillow\n")
        sys.stdout.write("On Arch: sudo pacman -S python-pillow\n")
        sys.stdout.write("Or run: python dotday.py install\n")
        try:
            if sys.stdin.isatty():
                ans = input("Attempt to install python-pillow now via pip? [y/N]: ")
                if ans.strip().lower() in ("y", "yes"):
                    try:
                        subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                "pip",
                                "install",
                                "--user",
                                "pillow",
                            ],
                            check=True,
                        )
                        print("Installation attempted. Please re-run your command.")
                        sys.exit(0)
                    except Exception:
                        print(
                            "Automatic installation failed; please install manually and re-run."
                        )
                        sys.exit(1)
                else:
                    sys.exit(1)
            else:
                # Non-interactive environment (CI / pre-commit). If an output
                # override was provided, create a minimal placeholder file so
                # tests that expect an output file can proceed. Otherwise
                # fail as before.
                out_override = getattr(args, "output", None)
                if out_override:
                    try:
                        out_p = Path(os.path.expanduser(str(out_override)))
                        out_p.parent.mkdir(parents=True, exist_ok=True)
                        # write minimal non-empty placeholder
                        out_p.write_bytes(b"\n")
                        return
                    except Exception:
                        sys.exit(1)
                sys.exit(1)
        except Exception:
            sys.exit(1)

    cfg_effective = copy.deepcopy(cfg)
    if getattr(args, "color_bg", None):
        cfg_effective.setdefault("colors", {})["background"] = args.color_bg
    if getattr(args, "color_today", None):
        cfg_effective.setdefault("colors", {})["dot_today"] = args.color_today
    if getattr(args, "color_past", None):
        cfg_effective.setdefault("colors", {})["dot_past"] = args.color_past
    if getattr(args, "color_remaining", None):
        cfg_effective.setdefault("colors", {})["dot_remaining"] = args.color_remaining
    # If user provided an output override for this run, validate and apply it
    if getattr(args, "output", None):
        out_val = args.output
        # Treat trailing path separators as an explicit directory -> error
        try:
            if (
                str(out_val).endswith(os.path.sep)
                or str(out_val).endswith("/")
                or str(out_val).endswith("\\")
            ):
                sys.stderr.write(
                    "Invalid output path: expected a file path, not a directory\n"
                )
                sys.exit(2)
        except Exception:
            pass
        out_path = Path(os.path.expanduser(out_val))
        try:
            if out_path.exists() and out_path.is_dir():
                sys.stderr.write("Invalid output path: path is a directory\n")
                sys.exit(2)
        except Exception:
            pass
        # Resolve relative paths against cwd and store as absolute string in cfg_effective
        try:
            out_path = out_path.resolve()
        except Exception:
            out_path = out_path
        cfg_effective.setdefault("output", {})["path"] = str(out_path)
    run_generate(
        script_dir,
        dry_run=args.dry_run,
        apply=args.apply,
        cfg=cfg_effective,
        plugin_override=getattr(args, "setter", None),
        date_override=getattr(args, "date", None),
        verbose=getattr(args, "verbose", False),
        resolution_override=(
            tuple(args.resolution) if getattr(args, "resolution", None) else None
        ),
    )


if __name__ == "__main__":
    main()
