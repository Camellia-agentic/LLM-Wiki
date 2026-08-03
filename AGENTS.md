# LLM Wiki 维护规范

你是此知识库的维护者。知识库由三层组成：

1. `raw/inbox/` 是用户在 Obsidian 中可编辑的收件箱。
2. `raw/sources/` 是从收件箱归档出的原始资料，只读且不可修改。
3. `wiki/` 是你维护的 Markdown Wiki，可创建和更新。
4. 本文件和 `purpose.md` 定义结构、边界和工作流程。

## 页面规范

- 每个 Wiki 页面使用 YAML frontmatter，至少包含 `title`、`type`、`sources`、`updated`。
- `sources` 使用 `raw/sources/` 下的相对路径；所有可验证事实必须保留来源。
- 页面间使用相对 Vault 根目录的 `[[wiki/页面路径，不含 .md]]` 链接，例如 `[[wiki/concepts/检索增强生成]]`。
- 不确定、冲突或待核实内容不要写成事实。只有带逐字原文引句并可在归档资料中定位的 `source_claim` 才可进入事实核验；缺漏、外部查证问题和无引句旧记录进入待补充队列。
- 不得复制整篇原始资料到 Wiki；写结论、关系、差异和可追溯摘要。
- 重新生成页面时保留未知 frontmatter 键和 `## 人工补充` 段；人工修改与草稿基线冲突时要求重新生成或人工处理，不静默覆盖。

## 导入流程

1. 从 `raw/inbox/` 读取已稳定保存的新资料，并创建可恢复的队列任务。
2. 第一阶段只提取证据、概念、实体、冲突与风险；将结果保存到 `.llm-wiki/analyses/`。
3. 第二阶段只能依据第一阶段分析生成资料摘要、概念/实体更新和关联页面，并写入 `.llm-wiki/drafts/<run_id>/`。
4. 只有 `draft accept` 或控制中心“应用”操作可以写入 `wiki/`、更新导航/搜索索引并追加 `wiki/log.md`；草稿基线变化时必须拒绝覆盖。
5. 草稿审批、事实核验和待补充是三类操作：草稿审批决定是否应用文件变更；事实核验只处理附带有效原文引句的 `source_claim`；缺漏和待查证问题进入另一队列。模型不得把无证据问题伪装为原文事实。

## 查询与健康检查

- 回答时优先检索 Wiki 页面，按 `[页面路径]` 标明依据；资料不足时明确说明。
- 有价值的跨资料分析应保存到 `wiki/queries/` 或 `wiki/synthesis/`。
- 删除资料只能走级联删除流程，保留其他来源共享的概念和实体。
- 定期检查断链、孤儿页面、缺失来源和明显冲突，并记录处理结果。

## 运行状态与验证

- `.llm-wiki/state.json`、`queue.json`、`reviews.json`、`analyses/`、`drafts/` 与 `search.db` 均为工具维护的运行时状态；不手工编辑。`wiki/reviews.md` 是事实核验与研究队列的可读镜像，以 `reviews.json` 为准。
- 移入回收站只会隐藏派生页面和检索结果，原始资料仍可通过 `trash restore` 或控制中心恢复；永久删除仍只能使用显式 `remove --yes`。
- 模型密钥只从当前进程的 `LLM_WIKI_API_KEY` 或 `--api-key` 读取；不要写入 Markdown、规则文件或日志。
- `watch` 只在启动时读取代码和环境变量。工具升级、更换模型地址或密钥后必须停止并重新启动监听器。
- 改动工具或文档后，按影响范围运行 `python -B -m unittest discover -s tests -v`、`python -B tools/wiki.py --help` 和 `python -B tools/wiki.py lint`，如实报告未通过项。
