from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from common import CONTENT, ROOT, read_json, write_json


def main() -> int:
    questions = read_json(CONTENT / "questions.json", []) or []
    experiences = read_json(CONTENT / "experiences.json", []) or []
    sources = read_json(CONTENT / "sources.json", []) or []
    domains = Counter(item["domain"] for item in questions)
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "questions": len(questions),
            "experiences": len(experiences),
            "sources": len(sources),
            "domains": dict(sorted(domains.items())),
        },
        "questions": [
            {
                "id": item["id"],
                "title": item["title"],
                "domain": item["domain"],
                "subtopic": item["subtopic"],
                "difficulty": item["difficulty"],
                "tags": item["tags"],
                "status": item["status"],
            }
            for item in questions
        ],
    }
    write_json(ROOT / "public" / "data" / "catalog.json", index)
    print(f"搜索索引已生成：{len(questions)} 道题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
