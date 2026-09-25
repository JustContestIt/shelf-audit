"""PII hygiene for logs and traces.

* phone numbers (agents authorise by phone) are masked in any string that goes to logs/LangSmith;
* photo bytes never go to traces (only sha256/pHash and size); LangSmith inputs are passed
  through `scrub` via the graph config;
* faces: optional blur for photos that are stored for the demo/review UI (OpenCV Haar cascade,
  only if opencv is installed — a bonus, not a dependency).
"""
from __future__ import annotations

import re
from typing import Any

PHONE_RE = re.compile(r"(?<!\d)(?:\+?7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
TOKEN_RE = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")          # Telegram bot token
KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b|\bsk-[A-Za-z0-9_-]{20,}\b")  # Google / OpenAI-style keys
B64_RE = re.compile(r"[A-Za-z0-9+/]{400,}={0,2}")


def mask_phone(s: str) -> str:
    return PHONE_RE.sub(lambda m: m.group(0)[:2] + "*" * max(0, len(m.group(0)) - 4) + m.group(0)[-2:], s)


def scrub(obj: Any) -> Any:
    if isinstance(obj, str):
        s = TOKEN_RE.sub("<bot-token>", obj)
        s = KEY_RE.sub("<api-key>", s)
        s = B64_RE.sub(lambda m: f"<base64 {len(m.group(0))} chars>", s)
        return mask_phone(s)
    if isinstance(obj, dict):
        return {k: ("<bytes>" if k in ("data", "photo_bytes") and isinstance(v, (str, bytes)) and len(v) > 200 else scrub(v))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(scrub(x) for x in obj)
    return obj


def blur_faces(im):  # PIL.Image -> PIL.Image
    try:
        import cv2
        import numpy as np
    except ImportError:
        return im
    arr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(40, 40))
    for x, y, w, h in faces:
        arr[y:y + h, x:x + w] = cv2.GaussianBlur(arr[y:y + h, x:x + w], (51, 51), 30)
    from PIL import Image

    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
