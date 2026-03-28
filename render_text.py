"""Text rendering helpers extracted from dotday.generate_wallpaper.

These functions are behavior-preserving copies of the originals and
are used by `dotday.py` via delegation to keep the main module smaller.
"""
import logging

try:
    from PIL import Image, ImageDraw, ImageFilter
except Exception as exc:
    Image = None
    ImageDraw = None
    ImageFilter = None
    logging.debug("dependency Pillow import failed: %s", exc)
from typing import Tuple


def _shear_image(img, shear=0.06):
    """Apply a horizontal shear to an RGBA image and return the transformed image."""
    if shear == 0:
        return img
    w, h = img.size
    shift = abs(int(h * shear))
    new_w = w + shift
    matrix = (1, shear, -min(0, shear) * h, 0, 1, 0)
    return img.transform((new_w, h), Image.AFFINE, matrix, resample=Image.BICUBIC)


def _measure_mask(font, text):
    """Return (w,h) from font.getmask(text) or None on failure.

    Callers may apply their original fallback heuristics when None is returned.
    """
    try:
        return font.getmask(text).size
    except Exception:
        return None


def draw_text_italic(img, pos, text, font, fill, shear=0.06):
    """Draw text with an italic-like shear by rendering to a temp image and shearing it."""
    if font is None:
        draw = ImageDraw.Draw(img)
        draw.text(pos, text, fill=fill)
        return
    mm = _measure_mask(font, text)
    if mm is not None:
        mask_w, mask_h = mm
    else:
        mask_w = (
            max(1, int(font.size * len(text) * 0.6))
            if hasattr(font, "size")
            else max(1, len(text) * 10)
        )
        mask_h = max(1, int(getattr(font, "size", 24)))
    shift = int(abs(shear) * mask_h) + 8
    tmp_w = mask_w + shift + 24
    tmp_h = mask_h + 12
    tmp = Image.new("RGBA", (tmp_w, tmp_h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    td.text((8, 6), text, font=font, fill=fill)
    sheared = _shear_image(tmp, shear=shear)
    try:
        img.paste(sheared, pos, sheared)
    except Exception:
        d = ImageDraw.Draw(img)
        d.text(pos, text, font=font, fill=fill)


def render_scaled_text(
    img, pos, text, font, fill, max_w, max_h, shear=0.06
) -> Tuple[int, int]:
    """Render `text` with `font`, scale it to fit within (max_w, max_h), apply shear and paste onto `img`.

    Returns (w_out, h_out) actual size of pasted raster.
    """
    if font is None:
        draw = ImageDraw.Draw(img)
        draw.text(pos, text, fill=fill)
        return (0, 0)

    mm = _measure_mask(font, text)
    if mm is not None:
        mask_w, mask_h = mm
    else:
        mask_w = max(10, len(text) * 12)
        mask_h = getattr(font, "size", 48)

    extra = int(abs(shear) * mask_h) + 8
    effective_w = mask_w + extra + 8
    effective_h = mask_h + 8

    scale_w = max_w / effective_w if effective_w > 0 else 1.0
    scale_h = max_h / effective_h if effective_h > 0 else 1.0
    scale = min(1.0, scale_w, scale_h)

    pad = 6
    base = Image.new("RGBA", (mask_w + pad * 2, mask_h + pad * 2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    bd.text((pad, pad), text, font=font, fill=fill)

    if scale < 0.999:
        new_w = max(1, int(base.width * scale))
        new_h = max(1, int(base.height * scale))
        base = base.resize((new_w, new_h), Image.LANCZOS)

    sheared = _shear_image(base, shear=shear)

    try:
        img.paste(sheared, pos, sheared)
    except Exception:
        ImageDraw.Draw(img).text(pos, text, font=font, fill=fill)

    return sheared.size


def rasterize_scaled_text(text, font, fill, max_w, max_h, shear=0.06):
    """Return a rasterized RGBA Image of `text` using `font`, scaled to fit (max_w, max_h) and sheared by `shear`.

    Does not paste into any target image.
    """
    if font is None:
        tmp = Image.new("RGBA", (max(1, int(max_w)), max(1, int(max_h))), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((0, 0), text, fill=fill)
        return tmp

    mm = _measure_mask(font, text)
    if mm is not None:
        mask_w, mask_h = mm
    else:
        mask_w = max(10, len(text) * 12)
        mask_h = getattr(font, "size", 48)

    pad_x = max(48, int(mask_w * 0.14))
    pad_y = max(36, int(mask_h * 0.22))

    base_w = mask_w + pad_x * 2 + int(abs(shear) * mask_h) + 160
    base_h = mask_h + pad_y * 2 + 96
    base = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    draw_x = pad_x
    draw_y = pad_y
    bd.text((draw_x, draw_y), text, font=font, fill=fill)

    bbox_pixels = base.getbbox()
    if bbox_pixels:
        x0, y0, x1, y1 = bbox_pixels
    else:
        try:
            tb = bd.textbbox((draw_x, draw_y), text, font=font)
            x0, y0, x1, y1 = tb
        except Exception:
            x0, y0, x1, y1 = draw_x, draw_y, draw_x + mask_w, draw_y + mask_h

    try:
        ascent, descent = font.getmetrics()
        desc_pad = max(14, int(descent * 1.2))
    except Exception:
        desc_pad = 20

    x0 = max(0, x0 - 32)
    y0 = max(0, y0 - 24)
    x1 = min(base.width, x1 + 32)
    y1 = min(base.height, y1 + desc_pad + 24)

    cropped = base.crop((x0, y0, x1, y1))

    eff_w = cropped.width + int(abs(shear) * cropped.height) + 12
    eff_h = cropped.height

    scale_w = max_w / eff_w if eff_w > 0 else 1.0
    scale_h = max_h / eff_h if eff_h > 0 else 1.0
    scale = min(1.0, scale_w, scale_h)

    if scale < 0.999:
        new_w = max(1, int(cropped.width * scale))
        new_h = max(1, int(cropped.height * scale))
        cropped = cropped.resize((new_w, new_h), Image.LANCZOS)

    sheared = _shear_image(cropped, shear=shear)
    return sheared
