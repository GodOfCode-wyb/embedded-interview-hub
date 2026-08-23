from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from collect import domain_matches, keyword_hits, score_candidate
from common import INBOX, ROOT, clean_text, normalize_url, read_json, stable_id, write_json
from deepseek import decode_page, robots_allowed

CONFIG_PATH = ROOT / "config" / "sources.json"
CANDIDATES_PATH = INBOX / "candidates.json"
FRONTIER_PATH = INBOX / "link-frontier.json"
REPORT_PATH = INBOX / "link-report.json"
USER_AGENT = "EmbeddedInterviewKnowledgeBot/2.0 (+public link discovery; metadata only)"

REJECTED_PATH_PARTS = {
    "login", "signin", "signup", "register", "auth", "account", "profile", "user", "users",
    "comment", "comments", "tag", "tags", "category", "search", "share", "about", "privacy",
    "terms", "contact", "issues", "pulls", "commits", "actions", "stargazers", "forks", "network",
    "releases", "archive", "download",
}
REJECTED_SUFFIXES = {
    ".7z", ".avi", ".css", ".csv", ".doc", ".docx", ".exe", ".gif", ".gz", ".ico",
    ".jpeg", ".jpg", ".js", ".json", ".mov", ".mp3", ".mp4", ".pdf", ".png", ".rar",
    ".rss", ".svg", ".tar", ".webp", ".xml", ".zip",
}


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current: dict | None = None
        self.links: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if not values.get("href") or "nofollow" in values.get("rel", "").lower():
            return
        self.current = {"href": values["href"], "parts": [], "title": values.get("title", "")}

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.current is not None:
            anchor = clean_text(" ".join(self.current["parts"]), 240) or clean_text(self.current["title"], 240)
            self.links.append({"href": self.current["href"], "anchor": anchor})
            self.current = None


def parse_links(html: str) -> list[dict]:
    parser = LinkParser()
    parser.feed(html)
    return parser.links


def allowed_host(host: str, allowed: set[str]) -> bool:
    return any(domain_matches(host, domain) for domain in allowed)


def safe_public_link(base_url: str, href: str, allowed: set[str]) -> str | None:
    raw = href.strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    try:
        url = normalize_url(urljoin(base_url, raw))
    except ValueError:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host or not allowed_host(host, allowed):
        return None
    path = unquote(parts.path).lower()
    segments = {value for value in re.split(r"[/_.-]+", path) if value}
    if segments & REJECTED_PATH_PARTS or any(path.endswith(suffix) for suffix in REJECTED_SUFFIXES):
        return None
    return url


def link_is_relevant(link: dict, seed: dict, config: dict) -> bool:
    text = f"{link.get('anchor', '')} {unquote(link.get('url', ''))}".lower()
    if keyword_hits(text, config.get("excluded_keywords", [])):
        return False
    interview_hits = keyword_hits(text, config.get("interview_keywords", []))
    scope_hits = keyword_hits(text, config.get("scope_keywords", []))
    seed_text = f"{seed.get('title', '')} {seed.get('summary', '')}".lower()
    seed_scope = keyword_hits(seed_text, config.get("scope_keywords", []))
    if interview_hits and (scope_hits or seed_scope):
        return True
    if seed.get("provider") == "stackexchange-search" and scope_hits:
        return True
    return len(set(scope_hits)) >= 2


def fetch_public_links(url: str, allowed: set[str]) -> list[dict]:
    if not robots_allowed(url):
        raise ValueError("robots.txt 不允许链接发现")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        final_url = normalize_url(response.geturl())
        final_host = (urlsplit(final_url).hostname or "").lower()
        if not allowed_host(final_host, allowed):
            raise ValueError("页面重定向到了未允许的域名")
        if response.headers.get_content_type() != "text/html":
            raise ValueError("页面不是 HTML")
        payload = response.read(1_000_000)
        html = decode_page(payload, response.headers.get_content_charset())

    result = []
    seen = set()
    for raw_link in parse_links(html):
        link_url = safe_public_link(final_url, raw_link["href"], allowed)
        if not link_url or link_url == final_url or link_url in seen:
            continue
        seen.add(link_url)
        result.append({"url": link_url, "anchor": raw_link.get("anchor", "")})
    return result


def parse_timestamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def due_for_scan(record: dict | None, rescan_days: int, now: datetime) -> bool:
    if not record:
        return True
    checked_at = parse_timestamp(record.get("last_checked_at"))
    return not checked_at or rescan_days <= 0 or (now - checked_at).days >= rescan_days


def main() -> int:
    config = read_json(CONFIG_PATH, {}) or {}
    candidates = read_json(CANDIDATES_PATH, []) or []
    allowed = {value.lower() for value in config.get("allowed_result_domains", [])}
    max_seeds = int(os.environ.get("MAX_LINK_SEED_PAGES", config.get("max_link_seed_pages", 40)))
    max_per_seed = int(os.environ.get("MAX_LINKS_PER_SEED", config.get("max_links_per_seed", 20)))
    max_discoveries = int(os.environ.get("MAX_LINK_DISCOVERIES", config.get("max_link_discoveries", 300)))
    rescan_days = int(os.environ.get("LINK_RESCAN_AFTER_DAYS", config.get("link_rescan_after_days", 30)))
    delay = float(os.environ.get("LINK_REQUEST_DELAY_SECONDS", config.get("link_request_delay_seconds", 1.0)))
    max_candidates = int(config.get("max_candidates", 5000))
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    frontier = read_json(FRONTIER_PATH, []) or []
    frontier_by_url = {item.get("url"): item for item in frontier if item.get("url")}
    by_url = {item.get("url"): item for item in candidates if item.get("url")}
    seeds = [
        item for item in candidates
        if item.get("status") in {"discovered", "promoted"}
        and item.get("url")
        and due_for_scan(frontier_by_url.get(item["url"]), rescan_days, now_dt)
    ]
    seeds.sort(key=lambda item: (-int(item.get("score", 0)), item.get("first_seen_at", "")))
    seeds = seeds[:max_seeds]
    failures = []
    discovered = 0

    for index, seed in enumerate(seeds):
        seed_url = seed["url"]
        added_for_seed = 0
        error = None
        try:
            links = fetch_public_links(seed_url, allowed)
            for link in links:
                if discovered >= max_discoveries or added_for_seed >= max_per_seed:
                    break
                if link["url"] in by_url or not link_is_relevant(link, seed, config):
                    continue
                title = clean_text(link.get("anchor") or urlsplit(link["url"]).path.rsplit("/", 1)[-1], 220)
                item = {
                    "title": title or link["url"],
                    "url": link["url"],
                    "summary": clean_text(f"公开页面关联链接；来源页面：{seed.get('title', '')}；锚文本：{title}"),
                    "published_at": None,
                }
                score, content_kind, status, signals = score_candidate(item, config)
                by_url[item["url"]] = {
                    "id": stable_id(item["url"], "candidate"),
                    **item,
                    "discovered_by": f"链接发现：{clean_text(seed.get('title', ''), 120)}",
                    "provider": "public-link-discovery",
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "score": score,
                    "content_kind": content_kind,
                    "signals": signals,
                    "status": status,
                }
                discovered += 1
                added_for_seed += 1
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            error = str(exc)[:240]
            failures.append({"url": seed_url, "error": error})
        frontier_by_url[seed_url] = {
            "url": seed_url,
            "last_checked_at": now,
            "discovered_count": added_for_seed,
            "error": error,
        }
        if discovered >= max_discoveries:
            break
        if index + 1 < len(seeds):
            time.sleep(delay)

    result = list(by_url.values())
    order = {"discovered": 0, "promoted": 1, "reference-only": 2, "out-of-scope": 3, "rejected": 4}
    result.sort(key=lambda item: (order.get(item.get("status", ""), 5), -int(item.get("score", 0))))
    result = result[:max_candidates]
    write_json(CANDIDATES_PATH, result)
    write_json(FRONTIER_PATH, sorted(frontier_by_url.values(), key=lambda item: item.get("last_checked_at", ""), reverse=True)[:max_candidates])
    write_json(REPORT_PATH, {
        "generated_at": now,
        "seed_pages_scanned": len(seeds),
        "new_candidates": discovered,
        "candidate_count": len(result),
        "status_counts": dict(sorted(Counter(item.get("status", "unknown") for item in result).items())),
        "failure_count": len(failures),
        "failures": failures,
        "policy": "只发现允许域名中的公开 HTML 链接；遵守 robots.txt，不绕过登录、付费墙、验证码或访问控制。",
    })
    print(f"链接扩展完成：扫描 {len(seeds)} 个公开页面，新增 {discovered} 条候选，{len(failures)} 个页面失败。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
