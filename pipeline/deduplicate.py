from __future__ import annotations

import re
from difflib import SequenceMatcher

from common import CONTENT, INBOX, read_json, stable_id, write_json

DUPLICATE_THRESHOLD = 0.62


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()


def bigrams(value: str) -> set[str]:
    text = normalize(value)
    return {text[index:index + 2] for index in range(max(0, len(text) - 1))} or {text}


def similarity(left: str, right: str) -> float:
    left_norm, right_norm = normalize(left), normalize(right)
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_set, right_set = bigrams(left_norm), bigrams(right_norm)
    union = left_set | right_set
    jaccard = len(left_set & right_set) / len(union) if union else 1.0
    return max(sequence, jaccard)


def main() -> int:
    enriched = read_json(INBOX / "enriched.json", []) or []
    candidates = read_json(INBOX / "candidates.json", []) or []
    existing = read_json(CONTENT / "questions.json", []) or []
    previous_review = read_json(INBOX / "review.json", []) or []
    previous_state = {
        item.get("review_id"): {
            "decision": item.get("decision", "pending"),
            "staged_question_id": item.get("staged_question_id"),
        }
        for item in previous_review
        if item.get("review_id")
    }
    candidates_by_id = {item.get("id"): item for item in candidates if item.get("id")}
    known = [(item["id"], item["title"]) for item in existing]
    review = []

    for record in enriched:
        result = record.get("result", {})
        if record.get("review_status") != "ai-draft" or not result.get("is_relevant"):
            continue
        candidate = candidates_by_id.get(record.get("candidate_id"), {})
        for question in result.get("questions", []):
            title = question.get("title", "").strip()
            if not title:
                continue
            review_id = stable_id(f"{record.get('source_url', '')}\n{title}", "review")
            scored = sorted(
                ((similarity(title, known_title), question_id, known_title)
                 for question_id, known_title in known),
                reverse=True,
            )
            best_score, best_id, best_title = scored[0] if scored else (0.0, None, None)
            state = previous_state.get(review_id, {})
            item = {
                "review_id": review_id,
                "candidate_id": record["candidate_id"],
                "source_url": record["source_url"],
                "source_title": record.get("source_title"),
                "candidate_score": candidate.get("score", 0),
                "relevance_reason": result.get("reason"),
                "experience": result.get("experience"),
                "question": question,
                "duplicate_score": round(best_score, 4),
                "possible_duplicate_id": best_id if best_score >= DUPLICATE_THRESHOLD else None,
                "possible_duplicate_title": best_title if best_score >= DUPLICATE_THRESHOLD else None,
                "recommendation": "possible-duplicate" if best_score >= DUPLICATE_THRESHOLD else "new-draft",
                "decision": state.get("decision", "pending"),
                "staged_question_id": state.get("staged_question_id"),
            }
            review.append(item)
            known.append((review_id, title))

    review.sort(key=lambda item: (
        item.get("decision") != "pending",
        item.get("recommendation") != "new-draft",
        item.get("duplicate_score", 1.0),
        -int(item.get("candidate_score", 0)),
    ))
    write_json(INBOX / "review.json", review)
    new_count = sum(
        1 for item in review
        if item.get("recommendation") == "new-draft" and item.get("decision") == "pending"
    )
    print(f"去重分析完成：{len(review)} 道候选题，其中 {new_count} 道新草稿可进入审核 PR。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
