"""Image embeddings for the visual RAG: SigLIP (shape/layout) + HSV histogram (label colour).

Both are exact ports of embedding_experiment/run_experiment.py (24.08), where the ensemble
"SigLIP + colour" reached 120/129 = 93% top-1 on six real frames while SigLIP alone had 79%
and colour alone 84%: the network separates brand/layout, the histogram separates shades
inside the pink zone. Any change here must be re-checked with `make rag-sanity`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.config import get_settings

SIGLIP_DIM = 768
HSV_DIM = 96  # 24 hue bins x 4 saturation bins
SIGLIP_CFG = {"size": 224, "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}


def _as_image(x: str | Path | Image.Image) -> Image.Image:
    if isinstance(x, Image.Image):
        return x.convert("RGB")
    return ImageOps.exif_transpose(Image.open(x)).convert("RGB")


def load_square(x, size: int, pad_color=(128, 128, 128)) -> Image.Image:
    im = _as_image(x)
    w, h = im.size
    s = max(w, h)
    canvas = Image.new("RGB", (s, s), pad_color)
    canvas.paste(im, ((s - w) // 2, (s - h) // 2))
    return canvas.resize((size, size), Image.BICUBIC)


def hsv_feat(x) -> np.ndarray:
    """24x4 hue x saturation histogram without glare/shadows, Hellinger-normalised (L2 = 1)."""
    im = _as_image(x).resize((96, 192), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) / 255.0
    hsv = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).convert("HSV"), dtype=np.float32) / 255.0
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = (s > 0.15) & (v > 0.12) & (v < 0.97)
    if mask.sum() < 50:
        mask = np.ones_like(s, bool)
    hb = (h[mask] * 24).clip(0, 23.999).astype(int)
    sb = (s[mask] * 4).clip(0, 3.999).astype(int)
    hist = np.zeros((24, 4), np.float32)
    np.add.at(hist, (hb, sb), 1.0)
    f = np.sqrt(hist.ravel() / max(1, mask.sum()))
    return f / (np.linalg.norm(f) + 1e-9)


class SiglipEmbedder:
    """SigLIP-base-patch16-224 vision tower in ONNX (CPU)."""

    def __init__(self, onnx_path: Path | str):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        self.outs = [o.name for o in self.sess.get_outputs()]
        self.mean = np.array(SIGLIP_CFG["mean"], np.float32).reshape(3, 1, 1)
        self.std = np.array(SIGLIP_CFG["std"], np.float32).reshape(3, 1, 1)

    def _prep(self, x) -> np.ndarray:
        im = load_square(x, SIGLIP_CFG["size"])
        arr = np.asarray(im, np.float32).transpose(2, 0, 1) / 255.0
        return (arr - self.mean) / self.std

    def __call__(self, x) -> np.ndarray:
        return self.batch([x])[0]

    def batch(self, xs: list, bs: int = 16) -> np.ndarray:
        out = []
        for i in range(0, len(xs), bs):
            x = np.stack([self._prep(v) for v in xs[i:i + bs]])
            res = dict(zip(self.outs, self.sess.run(None, {self.inp: x}), strict=True))
            for k in ("image_embeds", "pooler_output"):
                if k in res:
                    v = res[k]
                    break
            else:
                lhs = res.get("last_hidden_state", next(iter(res.values())))
                v = lhs[:, 0] if lhs.ndim == 3 else lhs
            v = v.reshape(len(x), -1).astype(np.float32)
            out.append(v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9))
        return np.concatenate(out) if out else np.zeros((0, SIGLIP_DIM), np.float32)


@lru_cache
def get_siglip() -> SiglipEmbedder | None:
    p = get_settings().siglip_onnx
    return SiglipEmbedder(p) if Path(p).exists() else None


def embed_pair(x, siglip: SiglipEmbedder | None = None) -> tuple[np.ndarray | None, np.ndarray]:
    siglip = siglip if siglip is not None else get_siglip()
    return (siglip(x) if siglip else None), hsv_feat(x)
