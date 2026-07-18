# AI Workspace 自我改进

`ai-workspace-improver` 是一个保守的 AI workspace 复盘 skill。它从本地
Copilot 与 Codex 对话的有限摘要中提取证据，再结合确定性的 workspace 检查，持续改进
skill、知识库、agent 与共享规则。

## 能做什么

- 采集未审阅的本地 Copilot 与 Codex JSONL 历史。首次复盘查看最近 90 天，之后只处理增量；同一 Codex session ID 的多个 rollout 文件只算一个逻辑会话。
- 在进入复盘前限制每条消息长度、遮蔽常见密钥；绝不把原始对话写入仓库、知识库、报告或审阅状态。
- 仅按 `workspace.toml` 盘点受管理的 AI 资产，不扫描机器上的无关文件。
- 通过 `ai-workspace status`、`doctor`、`apply --dry-run` 和单元测试形成 workspace 诊断证据。
- 先呈现有证据、改动最小的建议；只有你逐项选择后才会实施。
- 每项批准改动在 5 次相关逻辑会话或 30 天后（先到者）复查效果；调整与回退始终需要你确认。

它不会启动后台服务或定时任务，不会给代码打主观分数，也不会自动 reset、提交、推送或静默修复。

## 快速开始

在 AI 助手中输入 `每日回顾`、`自我改进`、`技能优化` 或 `工作区诊断`。skill 会先完成复盘并展示发现，再等待你选择要实施的项目。

也可以直接查看采集结果：

```bash
python scripts/collect_chat_history.py --source all --lookback-days 90
```

支持 `copilot`、`codex` 和 `all` 三种来源。显示数量为逻辑会话；`--mark-reviewed` 仍只推进底层 transcript 文件段游标，应在报告已展示后再使用。

## 建议门槛

- 调整 skill、agent 或全局规则：同一模式必须出现在两个独立会话中，或存在一个可明确预防的直接失败。
- 知识候选必须是已验证、可长期复用的事实。
- workspace 修复必须来自确定性检查，优先复用现有 `ai-workspace` 命令，不再新造修复工具。

## 效果复查

每项批准改动都会在本地 `skill_change_log.md` 记录基线、预期效果、可观察信号和“相关会话”的定义。到复查节点后，结论为保留、调整、回退或证据不足；后两类始终只是建议，不会自动改动资产。

## 隐私与本地状态

以下已被忽略的文件只保存在本地：`review_state.json`、`reviews/`、
`deferred_opportunities.md`、`skill_change_log.md`。它们保存游标、脱敏发现和审批记录，
不保存原始对话。

如果某个来源目录缺失或 transcript 格式变更，skill 会报告该来源降级，并继续使用可用来源和 workspace 诊断。

## 开发

运行采集器测试：

```bash
python -m unittest discover -s tests -v
```

测试只可使用合成 fixture；不得把真实聊天记录加入测试或文档。
