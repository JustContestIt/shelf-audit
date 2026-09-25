"""How reference images travel to the model.

* files_api (default live): upload once to the Gemini Files API, send `file_data.file_uri`.
  URIs live 48 h; the cache re-uploads anything older than 46 h. In n8n a single dead URI broke
  the whole request with 403 (incident 28.08) — here an upload is checked right before use.
* inline: base64 in the request (OpenRouter, offline, tests).
"""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path

import httpx

from app.catalog import Ref

TTL_S = 46 * 3600


class RefParts:
    def __init__(self, catalog_dir: Path, mode: str = "inline", api_key: str | None = None,
                 base_url: str = "https://generativelanguage.googleapis.com", cache_file: Path | None = None):
        self.catalog_dir = Path(catalog_dir)
        self.mode = mode
        self.api_key = api_key
        self.base_url = base_url.rstrip("/").removesuffix("/v1beta")
        self.cache_file = cache_file or (self.catalog_dir.parent / "cache" / "gemini_files.json")
        self._lock = threading.Lock()
        self._cache: dict = {}
        if self.cache_file.exists():
            try:
                self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._cache = {}

    def path(self, ref: Ref) -> Path:
        return self.catalog_dir / ref.path

    def __call__(self, ref: Ref) -> dict:
        if self.mode == "files_api" and self.api_key:
            return {"file_data": {"mime_type": ref.mime_type, "file_uri": self._uri(ref)}}
        if self.mode == "key":  # placeholder part for fingerprints/tests: no bytes, stable
            return {"file_data": {"mime_type": ref.mime_type, "file_uri": f"ref://{ref.key}"}}
        path = self.path(ref)
        if not path.exists():
            raise FileNotFoundError(f"reference image {ref.key} not found at {path} — run `make data` (fetch_data.py)")
        return {"inline_data": {"mime_type": ref.mime_type, "data": base64.b64encode(path.read_bytes()).decode("ascii")}}

    def _uri(self, ref: Ref) -> str:
        with self._lock:
            c = self._cache.get(ref.key)
            if c and time.time() - c["uploaded_at"] < TTL_S:
                return c["uri"]
            uri = self._upload(self.path(ref), ref.mime_type, ref.key)
            self._cache[ref.key] = {"uri": uri, "uploaded_at": time.time()}
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
            return uri

    def _upload(self, path: Path, mime: str, display_name: str) -> str:
        data = path.read_bytes()
        with httpx.Client(timeout=60) as c:
            start = c.post(f"{self.base_url}/upload/v1beta/files", headers={
                "x-goog-api-key": self.api_key, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)), "X-Goog-Upload-Header-Content-Type": mime,
            }, json={"file": {"display_name": display_name}})
            start.raise_for_status()
            up = start.headers["x-goog-upload-url"]
            r = c.post(up, headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"}, content=data)
            r.raise_for_status()
            return r.json()["file"]["uri"]
