from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
INBOX = CONTENT / "inbox"


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_url(raw_url: str) -> str:
    parts = urlsplit(raw_url.strip())
    ignored = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "spm", "from", "source", "share_token", "tracking_id",
    }
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in ignored]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def stable_id(value: str, prefix: str = "item") -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def clean_text(value: str, limit: int = 600) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def text_fingerprint(value: str) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
