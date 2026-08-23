from __future__ import annotations

import re
from difflib import SequenceMatcher

from common import CONTENT, INBOX, read_json, write_json


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
    existing = read_json(CONTENT / "questions.json", []) or []
    known = [(item["id"], item["title"]) for item in existing]
    review = []

    for record in enriched:
        if record.get("review_status") != "ai-draft":
            continue
        for question in record.get("result", {}).get("questions", []):
            scored = sorted(
                ((similarity(question.get("title", ""), title), question_id, title)
                 for question_id, title in known),
                reverse=True,
            )
            best_score, best_id, best_title = scored[0] if scored else (0.0, None, None)
            review.append({
                "candidate_id": record["candidate_id"],
                "source_url": record["source_url"],
                "question": question,
                "duplicate_score": round(best_score, 4),
                "possible_duplicate_id": best_id if best_score >= 0.62 else None,
                "possible_duplicate_title": best_title if best_score >= 0.62 else None,
                "decision": "merge-review" if best_score >= 0.62 else "new-review",
            })

    review.sort(key=lambda item: item["duplicate_score"], reverse=True)
    write_json(INBOX / "review.json", review)
    print(f"去重分析完成：{len(review)} 道候选题等待审核。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
