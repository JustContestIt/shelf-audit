"""Image helpers: EXIF-normalised loading, Telegram simulation, crops by box.

Chunking for images (ARCHITECTURE.md): one chunk = the crop of one unit by its box with
padding, aspect ratio preserved, long side 384 px. Group crops (a run of equal units on a
shelf) use the union box.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageOps

CROP_LONG_SIDE = 384
PAD_FRAC = 0.06


def load_image(src: str | Path | bytes) -> Image.Image:
    im = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    return ImageOps.exif_transpose(im).convert("RGB")


def to_jpeg_bytes(im: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def telegram_sim(im: Image.Image, long_side: int = 1280, quality: int = 80) -> Image.Image:
    """What Telegram delivers for a compressed photo: 1280 px long side, JPEG q≈80."""
    w, h = im.size
    s = long_side / max(w, h)
    if s < 1:
        im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
    return Image.open(io.BytesIO(to_jpeg_bytes(im, quality))).convert("RGB")


def box_to_px(box_2d: list[float], size: tuple[int, int]) -> tuple[float, float, float, float]:
    """Gemini [y0,x0,y1,x1] in 0..1000 -> pixel (x0,y0,x1,y1)."""
    w, h = size
    y0, x0, y1, x1 = box_2d
    return x0 * w / 1000, y0 * h / 1000, x1 * w / 1000, y1 * h / 1000


def crop_box(im: Image.Image, box_2d: list[float], pad: float = PAD_FRAC, long_side: int | None = CROP_LONG_SIDE) -> Image.Image:
    x0, y0, x1, y1 = box_to_px(box_2d, im.size)
    pw, ph = (x1 - x0) * pad, (y1 - y0) * pad
    c = im.crop((max(0, round(x0 - pw)), max(0, round(y0 - ph)), min(im.width, round(x1 + pw)), min(im.height, round(y1 + ph))))
    if long_side:
        s = long_side / max(c.size)
        if s < 1:
            c = c.resize((max(1, round(c.width * s)), max(1, round(c.height * s))), Image.BICUBIC)
    return c


def union_box(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def crop_xyxy_px(im: Image.Image, xyxy: list[float]) -> Image.Image:
    """Crop by pixel box [x0,y0,x1,y1] (format of the 24.08 experiment metadata)."""
    x0, y0, x1, y1 = xyxy
    return im.crop((max(0, int(x0)), max(0, int(y0)), min(im.width, int(x1)), min(im.height, int(y1))))
