# 本地面经导入区

把你拥有的面经文件临时放在本目录，然后在项目根目录执行：

```powershell
python pipeline/import_local.py --inspect
python pipeline/import_local.py --stage
```

也可以直接传入任意本地文件或目录，不必复制到项目中：

```powershell
python pipeline/import_local.py "D:\资料\嵌入式面经.md" --stage
```

支持 `.txt`、`.md`、`.json`、`.html`、`.docx`；PDF 需先执行 `python -m pip install pypdf`。`--inspect` 不调用 AI，只检查可读性和分段数量。执行 `python -B pipeline/import_local.py --save-api-key` 可在验证后把密钥保存到被 Git 忽略的本机 `.env.local`，以后无需重复输入；该文件在本机是明文，只适合个人电脑。导入器会先遍历全文提取所有题目纲要，再逐题生成完整答案；运行中断后重复命令即可从 `work/local-import/` 的断点继续。如不需要知识点扩题，添加 `--no-expand`。

本目录中的原始文件默认被 Git 忽略。流水线只保存 AI 结构化结果和内容指纹，不保存原文、绝对路径或文件名。知识点扩展题会明确标记，不会冒充原文直接问题。导入结果保持 `ai-draft`，提交前仍需检查技术准确性及隐私信息。
