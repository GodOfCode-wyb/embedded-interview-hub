# 本地面经导入区

把你拥有的面经文件临时放在本目录，然后在项目根目录执行：

```powershell
python pipeline/import_local.py --stage
```

也可以直接传入任意本地文件或目录，不必复制到项目中：

```powershell
python pipeline/import_local.py "D:\资料\嵌入式面经.md" --stage
```

支持 `.txt`、`.md`、`.json`、`.html`、`.docx`；PDF 需先执行 `python -m pip install pypdf`。

本目录中的原始文件默认被 Git 忽略。流水线只保存 AI 结构化结果和内容指纹，不保存原文、绝对路径或文件名。导入结果保持 `ai-draft`，提交前仍需检查技术准确性及隐私信息。
