from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from common import CONTENT, INBOX, read_json, stable_id, write_json

ALLOWED_DOMAINS = {
    "C 语言", "C++", "数据结构与算法", "操作系统", "计算机网络", "计算机体系结构",
    "STM32 / MCU", "RTOS", "Linux 系统编程", "Linux 驱动", "外设与协议",
    "编译与构建", "调试与测试", "物联网", "机器人", "音视频", "嵌入式 AI",
}
EXCLUDED_TERMS = {"汽车电子", "车载", "autosar", "fpga", "工业控制", "plc", "功能安全"}


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value or "").lower()


def bounded_text(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def string_list(value, max_items: int = 10, limit: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    return [bounded_text(item, limit) for item in value if bounded_text(item, limit)][:max_items]


def is_publishable(item: dict) -> bool:
    question = item.get("question") or {}
    title = str(question.get("title", "")).strip()
    source_url = str(item.get("source_url", "")).strip()
    source_title = str(item.get("source_title", ""))
    if item.get("recommendation") != "new-draft":
        return False
    if item.get("decision") not in {None, "pending", "approved"}:
        return False
    if float(item.get("duplicate_score", 1.0)) >= 0.62:
        return False
    if question.get("domain") not in ALLOWED_DOMAINS:
        return False
    if len(title) < 4 or not str(question.get("answer_short", "")).strip():
        return False
    if not str(question.get("question_evidence", "")).strip():
        return False
    if urlsplit(source_url).scheme not in {"http", "https"}:
        return False
    haystack = f"{title} {source_title}".lower()
    return not any(term.lower() in haystack for term in EXCLUDED_TERMS)


def main() -> int:
    limit = int(os.environ.get("MAX_STAGE_QUESTIONS", "40"))
    today = datetime.now(timezone.utc).date().isoformat()
    review = read_json(INBOX / "review.json", []) or []
    candidates = read_json(INBOX / "candidates.json", []) or []
    questions = read_json(CONTENT / "questions.json", []) or []
    sources = read_json(CONTENT / "sources.json", []) or []
    experiences = read_json(CONTENT / "experiences.json", []) or []
    updates = read_json(CONTENT / "updates.json", []) or []

    existing_titles = {normalize(item.get("title", "")) for item in questions}
    existing_question_ids = {item.get("id") for item in questions}
    existing_source_by_url = {
        item.get("url"): item.get("id") for item in sources if item.get("url")
    }
    existing_source_ids = {item.get("id") for item in sources}
    existing_experience_ids = {item.get("id") for item in experiences}
    candidates_by_id = {item.get("id"): item for item in candidates if item.get("id")}
    staged_by_candidate: dict[str, list[str]] = {}
    staged = 0

    for item in review:
        if staged >= limit or not is_publishable(item):
            continue
        question = item["question"]
        title = bounded_text(question["title"], 180)
        title_key = normalize(title)
        if title_key in existing_titles:
            item["decision"] = "duplicate"
            continue

        source_url = str(item["source_url"]).strip()
        source_id = existing_source_by_url.get(source_url) or stable_id(source_url, "source")
        if source_id not in existing_source_ids:
            provider = item.get("candidate_provider")
            is_technical_qa = provider == "stackexchange-search"
            sources.append({
                "id": source_id,
                "title": bounded_text(item.get("source_title") or title, 220),
                "kind": "公开技术问答" if is_technical_qa else "公开面经候选",
                "url": source_url,
                "trust": (
                    "公开技术问答的 AI 结构化草稿，需人工核验"
                    if is_technical_qa else "AI 结构化草稿，需人工核验"
                ),
            })
            existing_source_ids.add(source_id)
            existing_source_by_url[source_url] = source_id

        question_id = stable_id(f"{question.get('domain')}\n{title}", "question")
        if question_id in existing_question_ids:
            item["decision"] = "duplicate"
            continue
        follow_ups = string_list(question.get("follow_ups"), max_items=8, limit=240)
        pitfalls = string_list(question.get("pitfalls"), max_items=8, limit=280)
        tags = string_list(question.get("tags"), max_items=12, limit=60)
        subtopic = bounded_text(question.get("subtopic") or "待细分", 80)
        for value in (question.get("domain"), subtopic):
            if value and value not in tags:
                tags.append(value)

        questions.append({
            "id": question_id,
            "title": title,
            "domain": question["domain"],
            "subtopic": subtopic,
            "difficulty": question.get("difficulty") if question.get("difficulty") in {"基础", "进阶"} else "基础",
            "answer_short": bounded_text(question["answer_short"], 800),
            "answer_detail": bounded_text(question.get("answer_detail") or question["answer_short"], 3500),
            "follow_ups": follow_ups,
            "pitfalls": pitfalls,
            "tags": tags,
            "source_ids": [source_id],
            "status": "ai-draft",
            "updated_at": today,
        })
        existing_titles.add(title_key)
        existing_question_ids.add(question_id)
        item["decision"] = "staged"
        item["staged_question_id"] = question_id
        staged_by_candidate.setdefault(item["candidate_id"], []).append(question_id)
        candidate = candidates_by_id.get(item.get("candidate_id"))
        if candidate:
            candidate["status"] = "promoted"
        staged += 1

    for candidate_id, question_ids in staged_by_candidate.items():
        first = next((item for item in review if item.get("candidate_id") == candidate_id), None)
        experience = (first or {}).get("experience") or {}
        if not experience.get("role") or not experience.get("round"):
            continue
        experience_id = stable_id(candidate_id, "experience")
        if experience_id in existing_experience_ids:
            continue
        source_url = (first or {}).get("source_url")
        source_id = existing_source_by_url.get(source_url)
        experiences.append({
            "id": experience_id,
            "company": experience.get("company"),
            "role": experience["role"],
            "round": experience["round"],
            "date": experience.get("date"),
            "summary": bounded_text(
                experience.get("summary") or "公开面经中的问题已结构化为 AI 草稿，等待人工核验。",
                600,
            ),
            "question_ids": question_ids,
            "source_id": source_id,
        })
        existing_experience_ids.add(experience_id)

    if staged:
        updates.insert(0, {
            "date": today,
            "title": f"新增 {staged} 道待审核面试题",
            "description": "从公开面经和技术问答中提取并去重，答案状态为 AI 草稿，合并前需人工检查来源与技术准确性。",
        })
        write_json(CONTENT / "questions.json", questions)
        write_json(CONTENT / "sources.json", sources)
        write_json(CONTENT / "experiences.json", experiences)
        write_json(CONTENT / "updates.json", updates)

    write_json(INBOX / "review.json", review)
    write_json(INBOX / "candidates.json", candidates)
    print(f"候选发布准备完成：{staged} 道 AI 草稿已加入审核 PR。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
