# 内容维护约定

- `questions.json`：正式题目与答案。
- `experiences.json`：真实面经索引，不得补写未在来源中出现的公司、日期或结果。
- `sources.json`：原始面经与官方参考资料。
- `updates.json`：公开更新记录。
- `inbox/`：自动采集后尚未审核的候选内容。

题目状态：`source-only`、`ai-draft`、`reviewed`、`verified`、`outdated`。

任何自动化生成内容必须先通过结构校验；没有来源的信息不能标为真实面经，AI 整理内容不能自动标为 `verified`。
