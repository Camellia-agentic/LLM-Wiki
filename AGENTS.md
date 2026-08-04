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

## 规划与实现边界

- [docs/INTERACTION_AND_GRAPH_DESIGN.md](docs/INTERACTION_AND_GRAPH_DESIGN.md) 是采集、交互、Obsidian 集成、长文分析和知识图谱的目标设计；[docs/ROADMAP.md](docs/ROADMAP.md) 是实施状态权威。
- README 只能把代码和验证已支持的能力描述为当前功能；规划能力必须明确标记为未实现并链接路线图。
- 新的文件、URL、粘贴、插件或连接器入口必须进入统一的来源快照、Job、分析和草稿闸门，不得直接写入 Wiki。
- 外部来源必须保留稳定来源身份、不可变正文版本和采集元数据；变化的检查时间不得改写已有快照。
- 语义关系必须保留受控关系类型、目标页面和可定位来源证据；图谱只能是 Markdown Wiki 的派生视图。
- 在扩大长文或 URL 输入前必须覆盖分块分析，不能继续静默忽略第 14,000 字符之后的内容。
- Web、Obsidian 插件、剪藏器和 MCP 都是薄客户端：只调用版本化 API、展示状态和跳转，不复制采集、模型、草稿、图谱或删除逻辑。
- Obsidian 插件不得直接写 `.llm-wiki/`、运行 LLM、应用草稿或永久删除；只可读取客户端发现信息并调用 loopback API。
- `serve` 默认已经包含 inbox watcher；除非显式使用 `--no-watch` 和受控 worker，不得建议对同一 Vault 同时运行 `serve` 与 `watch`。

## 运行状态与验证

- `.llm-wiki/state.json`、`queue.json`、`reviews.json`、`analyses/`、`drafts/`、`search.db` 与规划中的 `control.json` 均为工具维护的运行时状态；不手工编辑。`wiki/reviews.md` 是可读镜像，以 `reviews.json` 为准。
- `control.json` 中的客户端 token 不得进入 Git、Markdown、URL、日志或截图；插件只读，不复制到仓库配置。
- 移入回收站只会隐藏派生页面和检索结果，原始资料仍可通过 `trash restore` 或控制中心恢复；永久删除仍只能使用显式 `remove --yes`。
- 模型端点与默认模型从仓库根目录 `config.toml` 读取（见 `config.toml.example`）；CLI 参数可临时覆盖。密钥只从 `config.toml` 中 `api_key_env` 指定的环境变量或 `--api-key` 读取，不要写入 Markdown、规则文件或日志。
- `watch` 和 `serve` 只在启动时读取代码、`config.toml` 和环境变量。工具升级、更换模型地址或密钥后必须停止并重新启动进程。
- 改动工具或文档后，按影响范围运行 `python -B -m unittest discover -s tests -v`、`python -B tools/wiki.py --help` 和 `python -B tools/wiki.py lint`，如实报告未通过项。
