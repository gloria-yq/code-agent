# 架构与不变量

## 控制循环

TUI、经典 CLI 和单次任务入口共用 `service.py` 装配的同一套运行时。
`CodingAgent.run` 为每次用户输入管理一个内层模型—工具循环，并在多次输入之间
保留规范消息历史。每次请求前只为 API 生成经过预算裁剪的视图，不改写原始历史。

若模型返回工具调用，循环会依次：

1. 解析 JSON 参数；
2. 校验必填字段、多余字段和基础类型；
3. 应用人工审批策略；
4. 调用本地处理器；
5. 把结果或结构化错误写入匹配的 `tool` 消息。

若模型只返回文本，该文本即为当前用户回合的最终答复。循环不使用服务端托管执行工具，
也不会把非结构化的模型文本直接当作 shell 命令。

## 展示层边界

Agent 通过 `AgentEvent` 发布与界面无关的事件，包括回合开始、模型流式分片、工具请求、
工具结果、终止和错误。TUI 只订阅这些事件，不实现第二套 Agent 循环。因此未来 Web 界面可以
复用配置服务、运行时装配和事件协议，无需改动工具或模型循环。

用户提交的文本由 TUI 在启动后台 Agent 之前立即写入对话区，`turn.started` 事件只负责运行时观测，不再重复渲染。工作区切换会完整重建 `Workspace`、工具注册表、系统提示和日志路径，不会在旧运行时上就地替换根目录。

## 可见程序生命周期

短时测试与构建继续使用同步的 `run_command`；需要用户实际操作的程序由独立的
`ProcessManager` 管理。它为交互式 CLI 打开系统终端，为本地 Web 服务等待端口就绪后打开
浏览器，为桌面程序启动 GUI 进程。管理器记录稳定的进程 ID、工作目录、状态、URL 和受限
日志，并向模型暴露启动、列举、重开预览和停止四个窄接口。

进程管理器属于工作区运行时：同一工作区重建模型连接时复用，切换工作区时不复用。TUI 在
切换、断开或退出前处理仍运行的进程，避免失去管理句柄。所有子进程都使用剥离模型凭据后
的环境；Web 预览只允许回环地址。这一层负责生命周期和凭据边界，不构成操作系统沙箱。

## 不变量

- The first canonical message is the system prompt; subsequent user turns share one history.
- 斜杠命令由展示层本地路由，永远不进入模型可见的对话。
- A local tool result always carries the originating `tool_call_id`.
- Unknown tools and invalid arguments become model-visible errors instead of process crashes.
- Tool arguments are validated locally instead of depending on provider-specific strict schemas.
- Tool handlers return JSON objects, keeping the model-facing protocol predictable.
- Filesystem paths are resolved through a single workspace boundary object.
- Existing files are never overwritten implicitly.
- An exact edit succeeds only when its old block occurs once.
- The command executor always has a timeout and output limit.
- Long-running applications use managed process IDs and never inherit model credentials.
- Context preparation deep-copies messages; compaction does not rewrite the event trail.
- 凭据从环境变量、外部 env 文件或操作系统凭据库解析，不写入公开配置或会话事件。
- File tools hide and reject credential `.env` files even when the model requests them directly.
- An interrupted user turn is rolled back to its starting message boundary, so partial tool-call
  sequences cannot corrupt the next request.

## 终止条件

The loop has independent stop reasons so a failure is diagnosable:

| Status | Meaning |
| --- | --- |
| `completed` | Model returned non-empty final text and no tool calls. |
| `model_error` | API retry policy was exhausted or the response was invalid. |
| `protocol_error` | Model returned neither text nor tool calls. |
| `tool_error_limit` | Three local tool calls failed consecutively. |
| `stalled` | The same tool request appeared in three consecutive turns. |
| `max_turns` | The configured turn budget was consumed. |
| `invalid_task` | The initial user task was empty. |
| `interrupted` | Esc interrupted a TUI user turn and its partial messages were rolled back. |

In interactive mode, a completed turn returns control to the prompt instead of terminating the
process. `/new` resets the canonical messages to the system prompt. Esc during model/tool work
returns an `interrupted` result; one-shot mode maps that result to exit code 130.

## 上下文策略

The canonical history is kept in memory and atomically snapshotted under the active workspace after
each user message, assistant response, and tool result. `ConversationStore` lists and restores those
snapshots independently from the append-only diagnostic event trail. A resume operation validates the
message roles and repairs a tool call that was durably recorded before a process ended but never received
a result. Before an API request, `ContextManager`:

1. bounds each large tool message;
2. estimates request size in serialized characters;
3. preserves the system prompt and the oldest conversation anchor;
4. keeps as much recent history as fits;
5. adds an explicit omission notice.

Character counting is deliberately transparent and provider-independent, but less accurate
than a model-specific tokenizer. A production extension could add tokenizer adapters without
changing the loop contract.

## 信任边界

The API is trusted to propose actions, not to execute them. The registry validates model
output before any handler runs. The workspace boundary protects file tools. Approval policy
mediates mutation categories. Shell pattern filtering provides a final local rejection layer.

The command tool is not a complete sandbox: a permitted shell command can still access data
available to the current operating-system user. For high-risk or untrusted tasks, run Code
Agent inside a container or disposable virtual machine.
