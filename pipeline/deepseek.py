from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common import CONTENT, INBOX, read_json, write_json

CANDIDATES_PATH = INBOX / "candidates.json"
OUTPUT_PATH = INBOX / "enriched.json"


def build_prompt(candidate: dict, known_titles: list[str]) -> str:
    nearby = "\n".join(f"- {title}" for title in known_titles[:160])
    return f"""你是嵌入式面试资料整理器。只根据给定搜索结果元数据提取，不访问网页，不补写不存在的公司、日期、面试结果或原文内容。

候选标题：{candidate.get('title', '')}
候选摘要：{candidate.get('summary', '')}
候选链接：{candidate.get('url', '')}
发现主题：{candidate.get('discovered_by', '')}

已有题目标题，用于判断潜在重复：
{nearby}

请返回 JSON 对象，格式必须为：
{{
  "is_relevant": true,
  "reason": "简短理由",
  "experience": {{"company": null, "role": null, "round": null, "date": null}},
  "questions": [
    {{
      "title": "标准化问题",
      "domain": "C 语言|C++|数据结构与算法|操作系统|计算机网络|计算机体系结构|STM32 / MCU|RTOS|Linux 系统编程|Linux 驱动|外设与协议|编译与构建|调试与测试|物联网|机器人|音视频|嵌入式 AI",
      "subtopic": "知识点",
      "difficulty": "基础|进阶",
      "answer_short": "只写可作为草稿的简答",
      "follow_ups": ["追问"],
      "possible_duplicate_title": null
    }}
  ]
}}

约束：输出 JSON；摘要没有明确题目时 questions 为空；不得把推测标为真实面经；答案必须标作草稿，不能声称已核验。"""


def call_api(api_key: str, base_url: str, model: str, prompt: str) -> dict:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出严格 JSON，不输出 Markdown。"},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 3000,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "EmbeddedInterviewKnowledgeBot/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    if not content or not content.strip():
        raise ValueError("DeepSeek 返回空内容")
    return json.loads(content)


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("未配置 DEEPSEEK_API_KEY，跳过 AI 整理。")
        return 0

    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    limit = int(os.environ.get("MAX_ENRICH_ITEMS", "10"))
    candidates = read_json(CANDIDATES_PATH, []) or []
    questions = read_json(CONTENT / "questions.json", []) or []
    known_titles = [item["title"] for item in questions]
    previous = read_json(OUTPUT_PATH, []) or []
    by_id = {item["candidate_id"]: item for item in previous if item.get("candidate_id")}
    pending = [item for item in candidates if item.get("status") == "discovered" and item["id"] not in by_id][:limit]

    for candidate in pending:
        last_error = None
        for attempt in range(3):
            try:
                result = call_api(api_key, base_url, model, build_prompt(candidate, known_titles))
                by_id[candidate["id"]] = {
                    "candidate_id": candidate["id"],
                    "source_url": candidate["url"],
                    "source_title": candidate["title"],
                    "model": model,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "review_status": "ai-draft",
                    "result": result,
                }
                break
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
                last_error = str(exc)[:400]
                time.sleep(2 ** attempt)
        else:
            by_id[candidate["id"]] = {
                "candidate_id": candidate["id"],
                "source_url": candidate["url"],
                "source_title": candidate["title"],
                "model": model,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "review_status": "failed",
                "error": last_error,
            }

    write_json(OUTPUT_PATH, sorted(by_id.values(), key=lambda item: item.get("generated_at", ""), reverse=True))
    print(f"AI 整理完成：本次处理 {len(pending)} 条，累计 {len(by_id)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
