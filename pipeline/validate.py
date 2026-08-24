from __future__ import annotations

from common import CONTENT, read_json

ALLOWED_STATUS = {"source-only", "ai-draft", "reviewed", "verified", "outdated"}
REQUIRED_QUESTION_FIELDS = {
    "id", "title", "domain", "subtopic", "difficulty", "answer_short", "answer_detail",
    "follow_ups", "pitfalls", "tags", "source_ids", "status", "updated_at",
}


def main() -> int:
    questions = read_json(CONTENT / "questions.json", []) or []
    experiences = read_json(CONTENT / "experiences.json", []) or []
    sources = read_json(CONTENT / "sources.json", []) or []
    errors: list[str] = []

    question_ids = [item.get("id") for item in questions]
    source_ids = {item.get("id") for item in sources}
    if len(question_ids) != len(set(question_ids)):
        errors.append("questions.json 存在重复 id")

    for item in questions:
        missing = REQUIRED_QUESTION_FIELDS - item.keys()
        if missing:
            errors.append(f"{item.get('id')}: 缺少字段 {sorted(missing)}")
        if item.get("status") not in ALLOWED_STATUS:
            errors.append(f"{item.get('id')}: 非法状态 {item.get('status')}")
        for follow_up in item.get("follow_ups", []):
            if isinstance(follow_up, str):
                continue
            if not isinstance(follow_up, dict) or not all(
                follow_up.get(key) for key in ("title", "answer_short", "answer_detail")
            ):
                errors.append(f"{item.get('id')}: 结构化追问字段不完整")
        for pitfall in item.get("pitfalls", []):
            if isinstance(pitfall, str):
                continue
            if not isinstance(pitfall, dict) or not all(
                pitfall.get(key) for key in ("title", "explanation", "correction")
            ):
                errors.append(f"{item.get('id')}: 结构化踩坑字段不完整")
        if int(item.get("answer_version", 0) or 0) >= 2:
            if len(str(item.get("answer_detail", ""))) < 250:
                errors.append(f"{item.get('id')}: 新版详解过短")
            if len(item.get("follow_ups", [])) < 2 or any(
                not isinstance(value, dict) for value in item.get("follow_ups", [])
            ):
                errors.append(f"{item.get('id')}: 新版答案至少需要 2 个带答案追问")
            if not item.get("pitfalls") or any(
                not isinstance(value, dict) for value in item.get("pitfalls", [])
            ):
                errors.append(f"{item.get('id')}: 新版答案至少需要 1 个结构化踩坑项")
        for source_id in item.get("source_ids", []):
            if source_id not in source_ids:
                errors.append(f"{item.get('id')}: 来源不存在 {source_id}")

    known_questions = set(question_ids)
    for item in experiences:
        if item.get("source_id") not in source_ids:
            errors.append(f"{item.get('id')}: 面经来源不存在")
        for question_id in item.get("question_ids", []):
            if question_id not in known_questions:
                errors.append(f"{item.get('id')}: 题目不存在 {question_id}")

    if errors:
        print(f"数据校验失败，共 {len(errors)} 项：")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"数据校验通过：{len(questions)} 道题，{len(experiences)} 组面经，{len(sources)} 个来源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
