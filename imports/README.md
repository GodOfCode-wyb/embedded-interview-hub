# 本地面经导入区

把你拥有的面经文件临时放在本目录，然后在项目根目录执行：

```powershell
python pipeline/import_local.py --inspect
python pipeline/import_local.py --stage
```

当前“嵌入式八股总结”资料建议显式限定目录，避免同时处理 `imports/` 中的旧文件：

```powershell
python -B pipeline/import_local.py "imports\三、嵌入式八股总结" --inspect
python -B pipeline/import_local.py "imports\三、嵌入式八股总结" --stage
```

也可以直接传入任意本地文件或目录，不必复制到项目中：

```powershell
python pipeline/import_local.py "D:\资料\嵌入式面经.md" --stage
```

支持 `.txt`、`.md`、`.json`、`.html`、`.docx`；PDF 需先执行 `python -m pip install pypdf`。`--inspect` 不调用 AI，只检查可读性和分段数量。执行 `python -B pipeline/import_local.py --save-api-key` 可在验证后把密钥保存到被 Git 忽略的本机 `.env.local`，以后无需重复输入；该文件在本机是明文，只适合个人电脑。

导入器会提取原文问题、问答标题和对应答案要点，Markdown 图片引用、data URI 与 `<img>` 会直接忽略，不处理图片文件。所有 `index.md` 和文件名以 `04 嵌入式场景题`（空格可省略）开头的资料也会按当前题库策略跳过。随后 AI 会先审核原答案：内容可用时保留，存在错误或深度、宽度不足时才纠正和扩展，并生成带答案追问。默认每个正文分段最多增加 1 道由原文知识点推导的扩展题，并明确标记；使用 `--no-expand` 可关闭。运行中断后重复命令即可从 `work/local-import/` 的断点继续；超长输出拆分后的成功子段也会立即保存，旧断点不会删除。

本目录中的原始文件默认被 Git 忽略。流水线只保存 AI 结构化结果和内容指纹，不保存原文、绝对路径或文件名。知识点扩展题会明确标记，不会冒充原文直接问题。导入结果保持 `ai-draft`，提交前仍需检查技术准确性及隐私信息。
