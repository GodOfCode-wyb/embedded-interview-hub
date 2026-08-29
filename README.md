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
python pipeline/discover.py
python pipeline/deepseek.py
python pipeline/deduplicate.py
python pipeline/promote.py
python pipeline/build_index.py
python pipeline/validate.py
```

`deepseek.py` 在未设置 `DEEPSEEK_API_KEY` 时会安全跳过。密钥只应保存在被 Git 忽略的本机 `.env.local`、本地环境变量或 GitHub Actions Secret 中。

流水线使用免费的公开入口组合搜寻：Bing 搜索 RSS、GitHub 公共仓库与 Markdown 代码搜索、GitLab 公共项目搜索、Stack Overflow 公共技术问答，以及已发现页面中的相关公开链接。搜索会分页进行，并把关联链接维护为可逐日扩张、定期复查的前沿；官方文档和产品主页只作为参考候选。

DeepSeek 会在 robots.txt 允许时读取公开页面的有限正文节选，但不会在仓库中保存原文，也不会绕过登录、付费墙、验证码、反爬或其他访问控制。无法公开读取的页面只保留标题、链接和搜索摘要。只有来源中明确出现的问题才能生成草稿；Stack Overflow 等技术问答只作为八股知识来源，不会伪装成公司面经。

`promote.py` 会把去重后、具有来源证据的候选题以 `ai-draft` 状态加入自动审核 PR。它们不会自动标为已核验；只有人工检查并合并 PR 后，才会进入 `main` 和线上题库。

## 导入本地面经

本地导入使用 DeepSeek 在你的电脑上读取并结构化文件，API 密钥不会进入网页。支持 TXT、Markdown、JSON、HTML 和 DOCX；PDF 可先安装可选依赖 `python -m pip install pypdf`。DOCX/PDF 默认支持至 25 MB，纯文本类文件默认支持至 5 MB。

可以直接指定文件或目录：

```powershell
npm run import:local -- "D:\资料\嵌入式面经.md" --stage
```

若不想每次输入，可先执行 `python -B pipeline/import_local.py --save-api-key`。脚本会安全提示输入，验证成功后保存到项目根目录的 `.env.local`，后续自动读取。该文件被 Git 忽略但在本机是明文，请只在个人电脑使用，不要手动提交或分享。

首次使用或遇到 HTTP 401 时，可先运行 `python -B pipeline/import_local.py --check-api`；它只验证密钥和模型，不处理文档。401 会立即终止，不再对后续分段重复请求。

也可以把文件临时放入 `imports/`，再执行：

```powershell
npm run import:local -- --stage
```

首次可先执行 `npm run import:local -- --inspect`，它只检查可读性和分段数量，不调用 AI。正式导入采用两阶段全量流程：先遍历正文，提取原文中明确出现的问题、问答标题和对应答案要点；再由 AI 审核原答案。准确且深度、宽度足够的内容会保留并整理表达，存在错误时纠正，缺少机制、边界、取舍、工程示例或排查步骤时才继续补充。Markdown 中的本地图片、data URI 和 `<img>` 会被忽略，不扫描、不复制，也不提交图片资源；所有 `index.md` 和以 `04 嵌入式场景题`（空格可省略）开头的文件不会进入导入流程。

默认在每个正文分段中最多增加 1 道由原文明确知识点推导的扩展题，并保存 `generation_kind: expanded` 和扩写依据，不会冒充原文问题。若只想收录原文问答，可使用 `--no-expand`；也可通过 `LOCAL_EXPANDED_QUESTIONS_PER_CHUNK=0|1|2` 调整数量。

长文档的结构化纲要和已完成答案会保存到被 Git 忽略的 `work/local-import/` 断点文件；超长输出递归拆分后的成功子段也会立即保存。网络中断或少量 AI 请求失败时，直接重复同一命令即可继续未完成题目，不会重新处理已完成答案或成功子段。

`--stage` 会自动执行去重、草稿入库、索引重建和内容校验。原始文件、绝对路径和文件名不会写入仓库；只保存内容指纹、面经元数据、题目和 AI 答案草稿。提交前仍应检查隐私信息和技术准确性。

## 深化已有答案

新题会按新版答案标准生成：标准简答、原理与工程详解、3 至 4 个带答案追问、2 至 3 个带纠正方案的踩坑项，并保存 AI 审核结论。旧题或深度不足的追问可在本地运行 `npm run answers:refine`，也可在 GitHub 仓库进入：

`Actions → Refine interview answers with AI → Run workflow`

首次建议 `limit` 填 `10`、`force` 保持关闭。深化器会优先处理仍是字符串的旧追问，其次处理数量不足、答案过短、缺少边界说明或尚无 AI 审核记录的题目。工作流会创建独立审核 PR，不会直接覆盖正式题库；检查并合并后，网页中的追问和踩坑项即可点击阅读完整答案。只有确需重新审核所有题目时才打开 `force`。

DeepSeek JSON 模式可能偶发返回空内容或被长度限制截断。脚本会检查 `finish_reason`、修复安全的尾逗号、用更紧凑的提示重试，并把仍失败的题目保留到下一轮；只要本轮至少有一道成功，就会为成功内容创建审核 PR。

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
   - Variable：`MAX_LINK_SEED_PAGES`（可选，每轮扫描的公开种子页面数，默认 40）
   - Variable：`MAX_LINKS_PER_SEED`（可选，每个页面最多发现的候选链接数，默认 20）
   - Variable：`MAX_LINK_DISCOVERIES`（可选，每轮关联链接新增上限，默认 300）
   - Variable：`LINK_RESCAN_AFTER_DAYS`（可选，关联链接复查周期，默认 30 天）
   - Variable：`LINK_REQUEST_DELAY_SECONDS`（可选，关联页面访问间隔，默认 1 秒）
   - Variable：`REFINE_BATCH_SIZE`（可选，答案深化每批题数，默认 1，优先保证输出完整）
   - Variable：`REFINE_WORKERS`（可选，并行请求数，默认 2）
   - Variable：`REFINE_MAX_ATTEMPTS`（可选，单批失败尝试次数，默认 2）
   - Variable：`REFINE_REQUEST_TIMEOUT_SECONDS`（可选，单次请求超时，默认 60 秒）
   - Variable：`REFINE_REQUEST_DELAY_SECONDS`（可选，答案深化请求间隔，默认 1 秒）

`collect.yml` 默认每天北京时间 21:00 运行，更新候选内容并创建审核 PR。

## 内容原则

- 不复制受版权保护的整篇文章。
- 不绕过登录、付费墙或反爬限制。
- 只读取允许域名的公开页面有限节选，不在仓库保存文章正文。
- 免费公开索引无法保证覆盖整个互联网；流水线以多入口、分页、链接扩展和每日增量尽可能提高覆盖率。
- 公司、日期、轮次和面试结果没有来源时保持未知。
- AI 内容标记为 `ai-draft`，只有经过资料核验的内容才能标记为 `verified`。
