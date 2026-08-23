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
python pipeline/validate.py
```

`deepseek.py` 在未设置 `DEEPSEEK_API_KEY` 时会安全跳过。密钥只应保存在本地环境变量或 GitHub Actions Secret 中。

## GitHub Pages

1. 将项目推送到 GitHub 仓库的 `main` 分支。
2. 在仓库 `Settings → Pages` 中将发布来源设为 `GitHub Actions`。
3. `deploy.yml` 会校验、构建并部署静态网站。
4. 如需每日 AI 整理，在 `Settings → Secrets and variables → Actions` 添加：
   - Secret：`DEEPSEEK_API_KEY`
   - Variable：`DEEPSEEK_MODEL`（可选）
   - Variable：`DEEPSEEK_BASE_URL`（可选）
   - Variable：`MAX_ENRICH_ITEMS`（可选）

`collect.yml` 默认每天北京时间 21:00 运行，更新候选内容并创建审核 PR。

## 内容原则

- 不复制受版权保护的整篇文章。
- 不绕过登录、付费墙或反爬限制。
- 公司、日期、轮次和面试结果没有来源时保持未知。
- AI 内容标记为 `ai-draft`，只有经过资料核验的内容才能标记为 `verified`。
