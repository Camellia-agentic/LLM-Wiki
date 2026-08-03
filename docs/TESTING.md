---
title: Local LLM Wiki 测试说明
status: current
updated: 2026-07-20
---

# 测试说明

## 自动化测试

```powershell
python -B -m unittest discover -s tests -v
python -B tools/wiki.py --help
python -B tools/wiki.py lint
```

当前 `tests/test_wiki.py` 覆盖：

- 无模型导入、搜索与健康检查
- 收件箱稳定检测、队列持久化、失败重试
- 两阶段重新提炼、跨资料综合、引用约束问答
- 草稿生成、应用、丢弃、基线冲突
- 人工补充和未知 frontmatter 保留
- 回收站恢复、显式别名与重复候选
- 审核项的原始资料/Wiki 正文详情、核实记录持久化
- 带原文引句的事实核验门槛、无引句问题降级、旧版审核项迁移
- 本机控制中心的状态、收件箱上传与审核详情 API

## 手工验收

1. 在配置模型的 PowerShell 中运行 `python tools/wiki.py serve`。
2. 打开 `http://127.0.0.1:8765/`，拖入一个 Markdown 或 TXT 文件。
3. 确认收件箱状态出现该文件，稳定时间后出现待确认草稿。
4. 打开草稿 Diff，应用后确认对应 Wiki 页面、索引和搜索结果出现；丢弃另一个草稿，确认 Wiki 页面不改变。
5. 在资料页添加 `## 人工补充` 和一个自定义 frontmatter 键，重新提炼后确认两者仍在。
6. 将一份已归档资料移入回收站，确认搜索不再命中；恢复后确认再次出现。
7. 导入一份含明确断言的资料，确认只有带原文逐字引句和行号的项目出现在“事实审核”；无引句问题出现在“待补充”。
8. 打开一个事实核验项，确认能看到原文引句、原始资料和 Wiki 页面；填写核实记录后标记“已处理”。打开一个待补充项，确认其明确标为无原文引句。
9. 运行 `python -B tools/wiki.py lint`，结果应为零断链、零孤儿页、零缺失来源。

测试不使用真实 API Key。模型路径使用替身响应；连接实际模型时只通过当前进程的 `LLM_WIKI_API_KEY` 或 `--api-key` 提供密钥。
