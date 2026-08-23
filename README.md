# 嵌入式面试知识库

面向嵌入式开发岗位的极简静态知识站，重点整理 C/C++、操作系统、计算机网络、STM32、RTOS、Linux 内核与驱动，以及物联网、机器人、音视频和嵌入式 AI 面经。

## 本地运行

```bash
npm ci
npm run dev
```

正式构建：

```bash
npm run content:validate
npm run typecheck
npm run build
```

静态文件输出到 `out/`。

## 内容更新

正式题库位于 `content/questions.json`，真实面经位于 `content/experiences.json`，来源记录位于 `content/sources.json`。自动发现的候选只进入 `content/inbox/`，不会直接伪装成正式题目。

手动运行流水线：

```bash
python pipeline/collect.py
python pipeline/deepseek.py
python pipeline/deduplicate.py
python pipeline/promote.py
python pipeline/build_index.py
python pipeline/validate.py
```

`deepseek.py` 在未设置 `DEEPSEEK_API_KEY` 时会安全跳过。密钥只应保存在本地环境变量或 GitHub Actions Secret 中。

流水线会优先选择含“面经、面试题、一面、二面”等信号且属于目标技术范围的页面；官方文档和产品主页只作为参考候选。DeepSeek 会在 robots.txt 允许时读取公开页面的有限正文节选，但不会在仓库中保存原文，也不会绕过登录、付费墙或站点限制。只有来源中明确出现的问题才能生成草稿。

`promote.py` 会把去重后、具有来源证据的候选题以 `ai-draft` 状态加入自动审核 PR。它们不会自动标为已核验；只有人工检查并合并 PR 后，才会进入 `main` 和线上题库。

## GitHub Pages

1. 将项目推送到 GitHub 仓库的 `main` 分支。
2. 在仓库 `Settings → Pages` 中将发布来源设为 `GitHub Actions`。
3. `deploy.yml` 会校验、构建并部署静态网站。
4. 如需每日 AI 整理，在 `Settings → Secrets and variables → Actions` 添加：
   - Secret：`DEEPSEEK_API_KEY`
   - Variable：`DEEPSEEK_MODEL`（可选）
   - Variable：`DEEPSEEK_BASE_URL`（可选）
   - Variable：`MAX_ENRICH_ITEMS`（可选）
   - Variable：`MAX_STAGE_QUESTIONS`（可选，每次最多进入审核 PR 的题目数）
   - Variable：`PAGE_FETCH_DELAY_SECONDS`（可选，公开页面读取间隔）
   - Variable：`REENRICH_AFTER_DAYS`（可选，默认 30 天后重新检查已发现来源）

`collect.yml` 默认每天北京时间 21:00 运行，更新候选内容并创建审核 PR。

## 内容原则

- 不复制受版权保护的整篇文章。
- 不绕过登录、付费墙或反爬限制。
- 只读取允许域名的公开页面有限节选，不在仓库保存文章正文。
- 公司、日期、轮次和面试结果没有来源时保持未知。
- AI 内容标记为 `ai-draft`，只有经过资料核验的内容才能标记为 `verified`。
