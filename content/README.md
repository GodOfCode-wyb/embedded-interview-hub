# 内容维护约定

- `questions.json`：正式题目与答案。
- `experiences.json`：真实面经索引，不得补写未在来源中出现的公司、日期或结果。
- `sources.json`：原始面经与官方参考资料。
- `updates.json`：公开更新记录。
- `inbox/`：自动采集后尚未审核的候选内容。

自动采集会从免费公开搜索、公共代码项目、公开技术问答和关联链接中发现资料，再按“面经/八股信号、岗位范围、来源站点”评分。普通官方文档只保留为参考，不送入 AI 题目提取。DeepSeek 只可从页面中明确出现的问题生成 `ai-draft`；可发布草稿会写入每日审核 PR，合并 PR 即表示人工确认可以进入网站。

题目状态：`source-only`、`ai-draft`、`reviewed`、`verified`、`outdated`。

新版答案使用 `answer_version: 2`。`follow_ups` 可保存带 `title`、`answer_short`、`answer_detail` 的结构化追问；`pitfalls` 可保存带 `title`、`explanation`、`correction` 的结构化误区。网页会把两类内容渲染为可点击的关联答案。为兼容历史题目，两处仍允许旧版字符串，但答案深化工作流会逐步迁移。

本地面经通过 `pipeline/import_local.py` 导入。原文和本地路径不得提交，正式来源使用 `url: null` 和不可逆的 `import_key` 识别；所有导入内容保持 `ai-draft`。

任何自动化生成内容必须先通过结构校验；没有来源的信息不能标为真实面经，AI 整理内容不能自动标为 `verified`。
