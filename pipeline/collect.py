from __future__ import annotations

import email.utils
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlencode, urlsplit

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


def fetch_github_repositories(query: str, limit: int) -> list[dict]:
    params = urlencode({
        "q": query,
        "per_page": min(limit, 30),
        "sort": "updated",
        "order": "desc",
    })
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/search/repositories?{params}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
    return payload.get("items", [])


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


def domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def build_feed_url(feed: dict) -> str:
    if feed.get("url"):
        return feed["url"]
    query = str(feed.get("query", "")).strip()
    if not query:
        raise ValueError(f"搜索源缺少 url 或 query：{feed.get('name', 'unknown')}")
    return f"https://cn.bing.com/search?format=rss&mkt=zh-CN&q={quote_plus(query)}"


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def score_candidate(item: dict, config: dict) -> tuple[int, str, str, list[str]]:
    host = (urlsplit(item.get("url", "")).hostname or "").lower()
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    interview_hits = keyword_hits(text, config.get("interview_keywords", []))
    scope_hits = keyword_hits(text, config.get("scope_keywords", []))
    reference_hits = keyword_hits(text, config.get("reference_keywords", []))
    excluded_hits = keyword_hits(text, config.get("excluded_keywords", []))

    domain_boost = 0
    for domain, boost in config.get("priority_domains", {}).items():
        if domain_matches(host, domain.lower()):
            domain_boost = max(domain_boost, int(boost))

    is_reference_domain = any(
        domain_matches(host, domain.lower())
        for domain in config.get("reference_domains", [])
    )
    score = (
        domain_boost
        + len(interview_hits) * 12
        + min(len(scope_hits), 5) * 4
        - len(reference_hits) * 10
        - (35 if is_reference_domain else 0)
    )
    minimum = int(config.get("minimum_interview_score", 25))

    if excluded_hits:
        status = "out-of-scope"
        content_kind = "excluded"
    elif interview_hits and scope_hits and score >= minimum:
        status = "discovered"
        content_kind = "interview"
    else:
        status = "reference-only"
        content_kind = "reference"

    signals = [
        *(f"interview:{value}" for value in interview_hits[:4]),
        *(f"scope:{value}" for value in scope_hits[:5]),
        *(f"reference:{value}" for value in reference_hits[:3]),
        *(f"excluded:{value}" for value in excluded_hits[:3]),
    ]
    return score, content_kind, status, signals


def main() -> int:
    config = read_json(CONFIG_PATH, {})
    allowed = set(config.get("allowed_result_domains", []))
    max_items = int(config.get("max_items_per_feed", 12))
    github_max_items = int(config.get("github_max_items_per_query", 10))
    max_candidates = int(config.get("max_candidates", 400))
    delay = float(config.get("request_delay_seconds", 1.0))
    previous = read_json(CANDIDATES_PATH, []) or []
    by_url = {item["url"]: item for item in previous if item.get("url")}
    now = datetime.now(timezone.utc).isoformat()
    failures = []

    def upsert(item: dict, discovered_by: str, provider: str) -> None:
        host = (urlsplit(item["url"]).hostname or "").lower()
        if allowed and not any(domain_matches(host, domain) for domain in allowed):
            return
        existing = by_url.get(item["url"], {})
        score, content_kind, status, signals = score_candidate(item, config)
        if existing.get("status") in {"promoted", "rejected"}:
            status = existing["status"]
        by_url[item["url"]] = {
            "id": existing.get("id") or stable_id(item["url"], "candidate"),
            "title": item["title"],
            "url": item["url"],
            "summary": item["summary"],
            "published_at": item.get("published_at"),
            "discovered_by": discovered_by,
            "provider": provider,
            "first_seen_at": existing.get("first_seen_at") or now,
            "last_seen_at": now,
            "score": score,
            "content_kind": content_kind,
            "signals": signals,
            "status": status,
        }

    for index, feed in enumerate(config.get("search_feeds", [])):
        try:
            payload = fetch(build_feed_url(feed))
            for item in parse_feed(payload)[:max_items]:
                upsert(item, feed["name"], "bing-rss")
        except Exception as exc:  # Keep the remaining feeds useful when one provider is unavailable.
            failures.append({"feed": feed.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(config.get("search_feeds", [])):
            time.sleep(delay)

    excluded_repositories = {
        value.lower() for value in config.get("excluded_repository_names", [])
    }
    github_queries = config.get("github_search_queries", [])
    github_delay = float(config.get("github_request_delay_seconds", 2.2))
    for index, search in enumerate(github_queries):
        try:
            for repository in fetch_github_repositories(search["query"], github_max_items):
                full_name = str(repository.get("full_name", ""))
                if not full_name or full_name.lower() in excluded_repositories:
                    continue
                description = repository.get("description") or ""
                topics = " ".join(repository.get("topics") or [])
                upsert({
                    "title": clean_text(full_name, 220),
                    "url": normalize_url(repository.get("html_url", "")),
                    "summary": clean_text(f"{description} {topics} 搜索命中：{search['name']}"),
                    "published_at": repository.get("updated_at"),
                }, search["name"], "github-search")
        except Exception as exc:
            failures.append({"feed": search.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(github_queries):
            time.sleep(github_delay)

    candidates = list(by_url.values())
    candidates.sort(key=lambda item: item.get("last_seen_at", ""), reverse=True)
    order = {"discovered": 0, "promoted": 1, "reference-only": 2, "out-of-scope": 3, "rejected": 4}
    candidates.sort(key=lambda item: (order.get(item.get("status", ""), 5), -int(item.get("score", 0))))
    candidates = candidates[:max_candidates]
    status_counts = Counter(item.get("status", "unknown") for item in candidates)
    write_json(CANDIDATES_PATH, candidates)
    write_json(INBOX / "collect-report.json", {
        "generated_at": now,
        "candidate_count": len(candidates),
        "status_counts": dict(sorted(status_counts.items())),
        "failure_count": len(failures),
        "failures": failures,
    })
    print(
        f"收集完成：{len(candidates)} 条候选，其中 "
        f"{status_counts.get('discovered', 0)} 条面经优先候选，{len(failures)} 个来源失败。"
    )
    return 0 if candidates or not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
