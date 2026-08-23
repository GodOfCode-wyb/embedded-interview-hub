from __future__ import annotations

import email.utils
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from html import unescape
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


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict | list:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        **(headers or {}),
    }
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read(4_000_000).decode("utf-8"))


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github_repositories(query: str, limit: int, page: int = 1) -> list[dict]:
    params = urlencode({
        "q": query,
        "per_page": min(limit, 30),
        "page": page,
        "sort": "updated",
        "order": "desc",
    })
    payload = fetch_json(
        f"https://api.github.com/search/repositories?{params}",
        github_headers(),
    )
    return payload.get("items", [])


def fetch_github_code(query: str, limit: int, page: int = 1) -> list[dict]:
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        raise ValueError("GitHub 代码搜索需要 GITHUB_TOKEN 或 GH_TOKEN")
    params = urlencode({"q": query, "per_page": min(limit, 100), "page": page})
    payload = fetch_json(f"https://api.github.com/search/code?{params}", github_headers())
    return payload.get("items", [])


def fetch_gitlab_projects(query: str, limit: int, page: int = 1) -> list[dict]:
    params = urlencode({
        "search": query,
        "simple": "true",
        "visibility": "public",
        "order_by": "last_activity_at",
        "sort": "desc",
        "per_page": min(limit, 100),
        "page": page,
    })
    payload = fetch_json(f"https://gitlab.com/api/v4/projects?{params}")
    return payload if isinstance(payload, list) else []


def fetch_stackexchange_questions(
    query: str,
    limit: int,
    page: int = 1,
    site: str = "stackoverflow",
) -> tuple[list[dict], int]:
    params = urlencode({
        "site": site,
        "q": query,
        "sort": "votes",
        "order": "desc",
        "pagesize": min(limit, 100),
        "page": page,
        "filter": "default",
    })
    payload = fetch_json(f"https://api.stackexchange.com/2.3/search/advanced?{params}")
    if not isinstance(payload, dict):
        return [], 0
    return payload.get("items", []), max(0, int(payload.get("backoff", 0)))


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return clean_text(value, 80)


def unix_date(value) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


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
    github_max_pages = int(config.get("github_max_pages_per_query", 1))
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
            for page in range(1, github_max_pages + 1):
                repositories = fetch_github_repositories(search["query"], github_max_items, page)
                for repository in repositories:
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
                if len(repositories) < min(github_max_items, 30):
                    break
                time.sleep(github_delay)
        except Exception as exc:
            failures.append({"feed": search.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(github_queries):
            time.sleep(github_delay)

    github_code_items = int(config.get("github_code_max_items_per_query", 30))
    github_code_pages = int(config.get("github_code_max_pages_per_query", 1))
    github_code_delay = float(config.get("github_code_request_delay_seconds", 6.5))
    github_code_queries = config.get("github_code_search_queries", [])
    for index, search in enumerate(github_code_queries):
        try:
            for page in range(1, github_code_pages + 1):
                matches = fetch_github_code(search["query"], github_code_items, page)
                for match in matches:
                    repository = match.get("repository") or {}
                    full_name = str(repository.get("full_name", ""))
                    if not full_name or full_name.lower() in excluded_repositories:
                        continue
                    path = str(match.get("path", ""))
                    upsert({
                        "title": clean_text(f"{full_name}/{path}", 220),
                        "url": normalize_url(match.get("html_url", "")),
                        "summary": clean_text(f"公开 Markdown 文档代码命中：{search['name']}；仓库 {full_name}"),
                        "published_at": None,
                    }, search["name"], "github-code-search")
                if len(matches) < min(github_code_items, 100):
                    break
                time.sleep(github_code_delay)
        except Exception as exc:
            failures.append({"feed": search.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(github_code_queries):
            time.sleep(github_code_delay)

    gitlab_items = int(config.get("gitlab_max_items_per_query", 50))
    gitlab_pages = int(config.get("gitlab_max_pages_per_query", 2))
    gitlab_delay = float(config.get("gitlab_request_delay_seconds", 0.8))
    gitlab_queries = config.get("gitlab_project_queries", [])
    for index, search in enumerate(gitlab_queries):
        try:
            for page in range(1, gitlab_pages + 1):
                projects = fetch_gitlab_projects(search["query"], gitlab_items, page)
                for project in projects:
                    full_name = str(project.get("path_with_namespace", ""))
                    description = project.get("description") or ""
                    topics = " ".join(project.get("topics") or project.get("tag_list") or [])
                    upsert({
                        "title": clean_text(full_name or project.get("name", ""), 220),
                        "url": normalize_url(project.get("web_url", "")),
                        "summary": clean_text(f"{description} {topics} 搜索命中：{search['name']}"),
                        "published_at": project.get("last_activity_at"),
                    }, search["name"], "gitlab-project-search")
                if len(projects) < min(gitlab_items, 100):
                    break
                time.sleep(gitlab_delay)
        except Exception as exc:
            failures.append({"feed": search.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(gitlab_queries):
            time.sleep(gitlab_delay)

    stack_items = int(config.get("stackexchange_max_items_per_query", 30))
    stack_pages = int(config.get("stackexchange_max_pages_per_query", 1))
    stack_delay = float(config.get("stackexchange_request_delay_seconds", 1.2))
    stack_queries = config.get("stackexchange_queries", [])
    for index, search in enumerate(stack_queries):
        try:
            for page in range(1, stack_pages + 1):
                questions, backoff = fetch_stackexchange_questions(
                    search["query"], stack_items, page, search.get("site", "stackoverflow")
                )
                for question in questions:
                    tags = " ".join(question.get("tags") or [])
                    upsert({
                        "title": clean_text(unescape(question.get("title", "")), 220),
                        "url": normalize_url(question.get("link", "")),
                        "summary": clean_text(
                            f"公开技术问答，面试八股参考：{search['name']}；标签 {tags}；"
                            f"得分 {question.get('score', 0)}"
                        ),
                        "published_at": unix_date(question.get("last_activity_date")),
                    }, search["name"], "stackexchange-search")
                if backoff:
                    time.sleep(backoff)
                if len(questions) < min(stack_items, 100):
                    break
                time.sleep(stack_delay)
        except Exception as exc:
            failures.append({"feed": search.get("name"), "error": str(exc)[:240]})
        if index + 1 < len(stack_queries):
            time.sleep(stack_delay)

    candidates = list(by_url.values())
    candidates.sort(key=lambda item: item.get("last_seen_at", ""), reverse=True)
    order = {"discovered": 0, "promoted": 1, "reference-only": 2, "out-of-scope": 3, "rejected": 4}
    candidates.sort(key=lambda item: (order.get(item.get("status", ""), 5), -int(item.get("score", 0))))
    candidates = candidates[:max_candidates]
    status_counts = Counter(item.get("status", "unknown") for item in candidates)
    provider_counts = Counter(item.get("provider", "unknown") for item in candidates)
    write_json(CANDIDATES_PATH, candidates)
    write_json(INBOX / "collect-report.json", {
        "generated_at": now,
        "candidate_count": len(candidates),
        "status_counts": dict(sorted(status_counts.items())),
        "provider_counts": dict(sorted(provider_counts.items())),
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
