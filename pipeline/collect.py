from __future__ import annotations

import email.utils
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit

from common import INBOX, ROOT, clean_text, normalize_url, read_json, stable_id, write_json

CONFIG_PATH = ROOT / "config" / "sources.json"
CANDIDATES_PATH = INBOX / "candidates.json"
USER_AGENT = "EmbeddedInterviewKnowledgeBot/1.0 (+GitHub Pages content index; metadata only)"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read(2_000_000)


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return clean_text(value, 80)


def item_text(element: ET.Element, names: list[str]) -> str:
    for child in element.iter():
        name = child.tag.split("}")[-1].lower()
        if name in names and child.text:
            return child.text.strip()
    return ""


def parse_feed(payload: bytes) -> list[dict]:
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if node.tag.split("}")[-1].lower() in {"item", "entry"}]
    result = []
    for entry in entries:
        link = item_text(entry, ["link"])
        if not link:
            for child in entry.iter():
                if child.tag.split("}")[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        if not link:
            continue
        result.append({
            "title": clean_text(item_text(entry, ["title"]), 220),
            "url": normalize_url(link),
            "summary": clean_text(item_text(entry, ["description", "summary", "content"])),
            "published_at": parse_date(item_text(entry, ["pubdate", "published", "updated"])),
        })
    return result


def main() -> int:
    config = read_json(CONFIG_PATH, {})
    allowed = set(config.get("allowed_result_domains", []))
    max_items = int(config.get("max_items_per_feed", 12))
    delay = float(config.get("request_delay_seconds", 1.0))
    previous = read_json(CANDIDATES_PATH, []) or []
    by_url = {item["url"]: item for item in previous if item.get("url")}
    now = datetime.now(timezone.utc).isoformat()
    failures = []

    for index, feed in enumerate(config.get("search_feeds", [])):
        try:
            payload = fetch(feed["url"])
            for item in parse_feed(payload)[:max_items]:
                host = (urlsplit(item["url"]).hostname or "").lower()
                if allowed and not any(host == domain or host.endswith(f".{domain}") for domain in allowed):
                    continue
                existing = by_url.get(item["url"], {})
                by_url[item["url"]] = {
                    "id": existing.get("id") or stable_id(item["url"], "candidate"),
                    "title": item["title"],
                    "url": item["url"],
                    "summary": item["summary"],
                    "published_at": item["published_at"],
                    "discovered_by": feed["name"],
                    "first_seen_at": existing.get("first_seen_at") or now,
                    "last_seen_at": now,
                    "status": existing.get("status", "discovered"),
                }
        except Exception as exc:  # Keep the remaining feeds useful when one provider is unavailable.
            failures.append({"feed": feed.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(config.get("search_feeds", [])):
            time.sleep(delay)

    candidates = sorted(by_url.values(), key=lambda item: item["last_seen_at"], reverse=True)
    write_json(CANDIDATES_PATH, candidates)
    write_json(INBOX / "collect-report.json", {
        "generated_at": now,
        "candidate_count": len(candidates),
        "failure_count": len(failures),
        "failures": failures,
    })
    print(f"收集完成：{len(candidates)} 条候选，{len(failures)} 个来源失败。")
    return 0 if candidates or not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
