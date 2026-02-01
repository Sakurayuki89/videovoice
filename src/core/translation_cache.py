"""
Translation Cache — stores translation + quality results on disk.

Cache key = hash of (original_text, source_lang, target_lang, sync_mode).
Each entry is a JSON file under static/cache/translations/.
"""
import hashlib
import json
import time
from pathlib import Path


class TranslationCache:
    def __init__(self, cache_dir: Path, expiration_days: int = 30):
        self.cache_dir = cache_dir
        self.expiration_seconds = expiration_days * 86400
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, text: str, source_lang: str, target_lang: str, sync_mode: str) -> str:
        raw = f"{text}|{source_lang}|{target_lang}|{sync_mode}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, text: str, source_lang: str, target_lang: str, sync_mode: str) -> dict | None:
        """Return cached entry or None if miss/expired."""
        key = self._make_key(text, source_lang, target_lang, sync_mode)
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("timestamp", 0) > self.expiration_seconds:
                path.unlink(missing_ok=True)
                return None
            return data
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
            return None

    def put(self, text: str, source_lang: str, target_lang: str, sync_mode: str,
            translated_text: str, quality_result: dict | None = None) -> None:
        """Store a translation result."""
        key = self._make_key(text, source_lang, target_lang, sync_mode)
        entry = {
            "timestamp": time.time(),
            "source_lang": source_lang,
            "target_lang": target_lang,
            "sync_mode": sync_mode,
            "translated_text": translated_text,
            "quality_result": quality_result,
        }
        try:
            self._path(key).write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except OSError as e:
            print(f"[Cache] Failed to write: {e}")

    def invalidate(self, text: str, source_lang: str, target_lang: str, sync_mode: str) -> bool:
        """Remove a cached entry. Returns True if deleted."""
        key = self._make_key(text, source_lang, target_lang, sync_mode)
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False
