# Code Agent：从零实现的编程智能体

Code Agent 是一个从零实现的本地编程智能体。默认界面是键盘优先的终端对话界面（TUI）：用户可以在同一会话中持续提出任务、追问结果、纠正方向和追加验证；模型文本会流式显示，工具调用、参数、状态和结果会以独立卡片呈现。

本项目**未使用任何 Agent 框架或 Agent SDK**。模型客户端、对话历史、工具定义、参数校验、本地执行、模型输出解析、上下文裁剪、权限确认、错误处理和循环终止均在本仓库中自行实现。Textual 只负责终端界面，`keyring` 和 `platformdirs` 只负责操作系统凭据库与用户配置目录，不参与 Agent 决策或工具执行。

## 主要功能

- 使用 `list_files` 浏览工作区目录。
- 使用 `search_text` 搜索 UTF-8 文本并返回文件名和行号。
- 使用 `read_file` 按行读取文件。
- 使用 `write_file` 创建文件或显式覆盖已有文件。
- 使用 `edit_file` 执行唯一文本块替换，避免误改多处内容。
- 使用 `run_command` 在本地执行测试、构建及其他命令。
- 使用 `launch_app` 把已完成的终端、Web 或桌面程序真正启动给用户操作，而不是只模拟运行记录。
- 默认提供多行输入、流式输出、工具卡片和审批弹窗的 TUI。
- 支持在界面内测试并保存 OpenAI/DeepSeek 连接，密钥进入操作系统凭据库。
- 提供持续交互式会话，后续输入自动继承此前对话、工具调用和执行结果。
- 支持 `/help`、`/new`、`/resume`、`/history`、`/processes`、`/status`、`/exit` 本地命令，不消耗模型请求。
- 将每次工具结果返回模型，使模型能够继续分析、纠错和验证。
- 对文件路径进行规范化，禁止文件工具访问指定工作区之外的位置。
- 支持三种权限模式，控制文件修改和命令执行是否需要人工确认。
- 拦截常见破坏性命令，并限制命令执行时间与输出长度。
- 模型密钥只供主进程中的 API 客户端使用，不会传给本地命令子进程。
- 对终端状态、命令输出、API 错误及 JSONL 日志中的已知密钥值统一脱敏。
- 在模型异常、连续工具错误、重复调用、达到轮次上限或用户中断时停止。
- 对超长工具输出和旧对话进行本地裁剪，控制模型请求上下文大小。
- 将运行过程记录为追加写入的 JSONL 事件日志，便于调试和复盘。

## 系统架构

```text
TUI / 经典 CLI / 未来 Web
   |
   v
中立事件层 <----> 会话状态 ------> Agent 回合循环 ------> 上下文管理 ------> OpenAI 兼容模型接口
   ^                                      |
   |                                      | 文本或工具调用
   |                                      v
   +---- 工具结果 <---- 权限策略 <---- 工具注册表
                                     /          \
                                  文件工具     命令工具
                                     |          |
                                     +-- 工作区边界 --+
```

一次用户输入构成一个“用户回合”，一个用户回合可以包含多次模型请求和工具执行。若模型返回工具调用，内层循环会依次完成以下操作：

1. 保存模型返回的 assistant 消息；
2. 解析工具参数 JSON；
3. 校验必填字段、额外字段和基础数据类型；
4. 执行权限策略；
5. 在本地调用对应工具；
6. 将成功结果或结构化错误作为 `tool` 消息写回历史；
7. 携带更新后的历史进入下一轮。

当模型不再请求工具并返回非空最终文本时，本回合结束并重新显示输入提示符；下一条自然语言输入会接续完整会话。更加详细的设计约束见 [`docs/architecture.md`](docs/architecture.md)。

## 环境要求

- Python 3.10 或更高版本
- 支持 OpenAI Chat Completions tool calling 协议的模型服务
- 对应模型服务的 API key
- 支持系统凭据库的桌面环境（推荐）；也可继续使用外部环境变量

## 安装

克隆公开仓库：

```bash
git clone https://github.com/gloria-yq/code-agent.git
cd code-agent
```

创建虚拟环境：

```bash
python -m venv .venv
```

激活虚拟环境：

```bash
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

安装本地命令：

```bash
python -m pip install -e .
```

## 模型配置

首次运行 `code-agent --workspace .` 时，如果尚未配置凭据，程序会自动打开连接弹窗。选择 DeepSeek 或 OpenAI，填入 API key、Base URL 和模型名，然后选择“Test and save”。程序只有在真实 API 连接测试成功后才保存配置。
也可在任意时候输入 `/connect` 重新配置。这是 TUI 的主要鉴权入口：配置成功一次后，凭据属于当前操作系统用户，不属于某个工作区，后续切换到没有 `.env` 的项目也可继续使用。

- API key 保存在操作系统凭据库，不写入项目或 `settings.json`。
- Base URL、模型、思考模式等非敏感配置保存在用户配置目录。
- `/config` 只显示非敏感配置和凭据来源，不显示密钥。
- `/disconnect` 可删除当前服务商的已保存凭据。
- 最近工作区只保存目录路径，不保存项目内容或密钥。

为了无界面环境和自动化兼容，仍然支持环境变量，其优先级高于系统凭据库：

推荐通过系统环境变量提供配置：

```bash
# macOS / Linux
export OPENAI_API_KEY="你的密钥"
export OPENAI_MODEL="模型名称"
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY = "你的密钥"
$env:OPENAI_MODEL = "模型名称"
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
```

如果必须使用配置文件，应把它放在待处理工作区之外，再通过
`CODE_AGENT_ENV_FILE` 指定其位置。这样 Agent 执行的项目代码无法通过普通工作区文件
访问直接读到配置文件。例如在 Windows PowerShell 中：

```powershell
New-Item -ItemType Directory -Force "$env:APPDATA\code-agent"
Copy-Item .env.example "$env:APPDATA\code-agent\config.env"
$env:CODE_AGENT_ENV_FILE = "$env:APPDATA\code-agent\config.env"
```

然后仅在工作区外的 `config.env` 中填写：

```text
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=模型名称
```

macOS / Linux 可把该文件放在 `~/.config/code-agent/config.env`，并执行
`export CODE_AGENT_ENV_FILE="$HOME/.config/code-agent/config.env"`。为方便入门，程序仍兼容
工作区根目录中的 `.env`，但处理不可信代码时不推荐这种放置方式。

程序只读取白名单配置项，且已有系统环境变量优先于配置文件。`.env` 已被 Git 忽略，
文件工具和命令工具也会主动拒绝直接访问该文件。真实密钥不得提交到仓库、写入文档或
出现在公开日志中。

如使用其他 OpenAI 兼容服务，请修改 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`。基础地址应指向服务公布的 API 根路径，程序会自动追加 `/chat/completions`。

### DeepSeek 官方 API

DeepSeek 使用 OpenAI 兼容的 Chat Completions 消息与工具格式，但思考模式还有额外要求。项目内置 `deepseek` 兼容模式，会保留并回传 `reasoning_content`；启用思考模式时不会发送 DeepSeek 不接受的 `tool_choice` 字段。

```env
CODE_AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_THINKING=enabled
```

使用 DeepSeek 官方地址或只设置 `DEEPSEEK_API_KEY` 时，默认的 `auto` 模式也会自动识别。若所用模型或兼容网关不支持思考模式，可设置 `DEEPSEEK_THINKING=disabled`。也可以继续使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL` 指向 DeepSeek，但显式使用 `DEEPSEEK_*` 更容易辨认。

## 运行方法

进入默认 TUI：

```bash
code-agent --workspace .
```

在输入区中，`Enter` 发送，`Shift+Enter` 换行，`Ctrl+Enter` 也作为兼容发送快捷键；`Ctrl+O` 选择工作区，`Esc` 请求停止当前回合，`Ctrl+C` 保留给终端复制，`Ctrl+Q` 退出。用户消息在发送后会立即出现在对话区；工具执行会显示 `RUNNING`、`DONE` 或 `FAILED` 状态。

界面内命令：

```text
/connect
/models
/config
/permissions
/resume
/workspace
/processes
/disconnect
/new
/status
/help
/exit
```

每条自然语言输入都复用此前消息和工具结果。以下命令完全在本地处理，不会发送给模型：

| 命令 | 作用 |
| --- | --- |
| `/connect` | 测试并保存模型服务配置。 |
| `/models` | 选择或输入当前服务支持的模型。 |
| `/config` | 显示不含密钥的当前配置。 |
| `/permissions` | 在 TUI 内切换并保存权限模式，立即生效且不清空对话。 |
| `/resume` | 浏览当前工作区保存的历史会话，查看摘要并恢复完整上下文。 |
| `/workspace` | 从路径、最近目录或目录树选择新工作区。 |
| `/processes` | 查看当前工作区由 Agent 启动的程序，可重新打开 Web 预览或停止进程。 |
| `/disconnect` | 从系统凭据库移除当前凭据。 |
| `/help` | 显示交互命令帮助。 |
| `/new` | 清空当前对话，但保留系统提示和工作区配置。 |
| `/history` | `/resume` 的别名；打开当前工作区的历史会话选择器。 |
| `/status` | 显示用户回合、模型请求、工具调用和消息数量。 |
| `/exit` | 结束交互会话，也可使用 `/quit` 或 `/q`。 |

切换工作区时，程序会先验证目录，然后重建文件工具、命令工具、系统提示和会话日志边界。旧对话不会带入新工作区，执行任务期间也不允许切换。
如果当前只能从旧工作区的 `.env` 取得密钥，而新工作区没有凭据，TUI 会自动打开连接表单。用户明确输入密钥并通过测试后，程序将其保存到系统凭据库并自动继续原工作区切换。程序不会在未经授权的情况下把 `.env` 密钥迁移到全局凭据库。

如需回退到单行的经典命令行会话：

```bash
code-agent --workspace . --classic
```

也可以传入任务，执行完成后直接退出，适合脚本和自动化：

```bash
code-agent "检查这个项目，修复失败的测试，并说明修改内容"
```

指定其他工作区：

```bash
code-agent --workspace ../sample-project "增加输入校验，补充测试并运行测试套件"
```

尚未安装命令时，也可以直接运行模块：

```bash
python -m code_agent --workspace ../sample-project "完成指定编程任务"
```

主要参数：

```text
--workspace PATH
--model MODEL
--base-url URL
--provider {auto,openai,deepseek}
--deepseek-thinking {enabled,disabled}
--max-turns N
--approval-mode {suggest,auto-edit,full}
--no-session-log
--classic
```

## 权限模式

在 TUI 内输入 `/permissions`，可以直接选择并保存权限模式；切换会立即作用于后续工具调用，不需要退出，也不会清空当前对话。执行任务期间不能切换。

| 模式 | 文件写入与编辑 | 命令执行 |
| --- | --- | --- |
| `suggest` | 每次询问 | 每次询问 |
| `auto-edit`（默认） | 自动允许 | 每次询问 |
| `full` | 自动允许 | 自动允许 |

无论选择哪种模式，程序都会拒绝已识别的破坏性命令。该过滤器属于纵深防护措施，并不是完整的操作系统沙箱。处理不可信项目时，应使用一次性 Git checkout、容器或虚拟机。

## 本地工具

### `list_files`

递归列出工作区中的目录和文件，并跳过 `.git`、虚拟环境、依赖目录、会话目录及凭据配置。

### `search_text`

对 UTF-8 文件执行字面量搜索，返回匹配路径、行号和行内容，可设置大小写敏感及最大结果数。

### `read_file`

读取 UTF-8 文件，支持指定起止行。二进制文件、工作区外路径和凭据配置会被拒绝。

### `write_file`

创建 UTF-8 文件。若目标文件已存在，模型必须显式传入 `overwrite=true`，避免无意覆盖。

### `edit_file`

将旧文本块替换为新文本块。旧文本必须在文件中恰好出现一次，否则工具返回错误并要求模型重新读取文件。

### `run_command`

在工作区目录中执行前台命令，返回退出码、标准输出和标准错误。命令子进程保留 `PATH`、
`SystemRoot`、虚拟环境等正常工具链配置，但会剥离名称包含 API key、token、secret、
password、credential 的环境变量及 `CODE_AGENT_ENV_FILE`。命令具有超时及输出上限，
常见破坏性模式和对 `.env` 的直接访问会被拒绝。

### `launch_app`、`list_processes`、`open_preview`、`stop_process`

当用户明确要求“运行并展示给我”时，Agent 会先完成必要的测试，再根据程序类型选择展示方式：

- 交互式 CLI 使用 `terminal` 模式，在新的系统终端中启动，用户可以直接输入和操作；
- 本地 Web 应用使用 `web` 模式，等待指定端口可连接后打开默认浏览器；
- 原生桌面程序使用 `desktop` 模式，启动其 GUI 进程。

Web 预览只接受 `localhost`、`127.0.0.1` 或 `::1` 地址，不会代替用户打开任意外部网址。启动命令使用所选工作区作为目录，子进程不会继承模型 API key。TUI 中可输入 `/processes` 查看运行状态、最近日志、重新打开 Web 页面或停止程序。切换工作区、断开模型连接或退出 TUI 时，如果仍有程序运行，界面会先给出明确提示，确认后再停止这些进程。

例如可以直接提出：

```text
运行这个井字棋并展示给我，我要自己操作；如果启动失败，请读取错误并修复后重试。
```

启动和停止都属于命令执行权限：`suggest` 与 `auto-edit` 模式会显示审批，`full` 模式自动允许。

## 循环终止条件

| 状态 | 含义 |
| --- | --- |
| `completed` | 模型返回非空最终文本，本用户回合结束；交互会话仍可继续。 |
| `model_error` | 模型 API 请求或响应解析发生不可恢复错误。 |
| `protocol_error` | 模型既未返回文本，也未返回工具调用。 |
| `tool_error_limit` | 工具连续失败达到设定上限。 |
| `stalled` | 模型连续三轮提出相同的工具请求。 |
| `max_turns` | 达到配置的最大轮次数。 |
| `invalid_task` | 用户任务为空。 |
| `interrupted` | 用户在 TUI 回合执行期间按下 Esc，半截消息被回滚。 |

TUI 在执行回合时按下 Esc 会设置协作式取消信号；当前模型流或本地工具返回到安全边界后，回合的半截消息会被回滚，避免污染后续上下文。Ctrl+C 不再由 TUI 绑定，可用于终端文本复制。已经进入的单个阻塞系统调用不会被强制杀死；单次任务模式仍可由终端中断并以退出码 130 结束。

## 上下文管理

Agent 在内存中保留整个交互会话的完整消息历史，并在每次用户消息、模型响应和工具结果之后，将可恢复快照原子写入当前工作区的 `.code-agent/conversations/`。重新打开 TUI 后输入 `/resume`（或 `/history`），即可按更新时间选择会话、查看最近对话预览并恢复完整模型上下文。`/new` 会开始新的会话，但不会删除旧会话。

会话文件与诊断日志用途不同：会话文件用于恢复模型消息链，`.code-agent/sessions/` 中的 JSONL 只用于审计和排错。异常退出时，如果最后一条工具调用还没有结果，恢复逻辑会补入明确的中断结果，要求 Agent 重新检查工作区状态后再行动，避免向模型发送不完整的 tool-calling 序列。

每次请求模型之前，上下文管理器会：

1. 深拷贝当前消息，避免裁剪过程修改原始历史；
2. 截断过长的工具输出；
3. 估算序列化消息的字符数；
4. 始终保留系统提示和最早的会话锚点；
5. 尽可能保留近期完整消息；
6. 插入明确的历史省略提示。

当前实现使用字符预算而不是模型专用 tokenizer，以保持逻辑透明并兼容不同服务。其不足是 token 估算不如专用 tokenizer 精确。

## 错误处理与日志

- API 限流、超时和部分服务器错误会进行有限次数的指数退避重试。
- 工具参数错误不会导致主进程崩溃，而会作为结构化结果返回模型纠正。
- 每次模型请求、响应、工具调用、工具结果和最终状态都会写入 JSONL 事件。
- 默认日志目录为工作区中的 `.code-agent/sessions/`，该目录不会提交到 Git。
- 可恢复对话保存在 `.code-agent/conversations/`，同样不会提交到 Git；`--no-session-log` 只关闭诊断日志，不关闭会话恢复。
- 已知的模型 API key 会在写入日志前递归替换为 `[REDACTED]`；任务内容、工具参数和工具输出仍可能包含其他项目数据，不应公开分享未经检查的日志。

## 测试

测试使用 Python 内置的 `unittest` 和模拟模型客户端，不需要 API key 或网络访问：

```bash
python -m unittest discover -v
```

测试覆盖：

- 模型—工具—模型完整往返；
- 连续用户追问复用同一消息历史、`/new` 重置与 Esc 回滚；
- 会话原子保存、工作区内列表、预览、跨进程恢复和中断工具链修复；
- 交互命令本地路由且不会误发给模型；
- 正常完成、重复调用、最大轮次和工具错误上限；
- 工具参数 JSON 解析及基础类型校验；
- 文件创建、读取、唯一替换和文本搜索；
- 工作区路径逃逸攻击；
- `.env` 隐藏和拒绝读取；
- 命令执行及破坏性命令拒绝；
- 可见应用的跨平台启动、本地 Web 就绪检查、日志读取、重新打开和进程树停止；
- 上下文裁剪且不修改原始消息；
- JSONL 事件日志；
- Chat Completions 请求载荷和返回解析；
- `.env` 白名单加载及环境变量优先级。
- 系统凭据库与公开配置分离、配置优先级和失败回滚。
- SSE 流式文本、思考内容和分片工具参数组装。
- TUI 无头挂载、本地命令与首次连接弹窗。

GitHub Actions 会在 Windows 与 Linux、Python 3.10 与 3.13 的组合上运行完整测试。

## 演示项目

`examples/todo_app` 是一个独立的小型待办事项命令行项目，可用于验证 Agent 的端到端能力。可将该目录复制到临时位置，然后向 Agent 提交以下任务：

```text
为待办事项 CLI 增加 --status pending|done|all 过滤功能；默认值保持 all；
补充对应测试，更新项目说明，并运行完整测试套件。
```

该任务需要 Agent 浏览仓库、理解现有代码、修改多个文件并运行测试。提交到仓库中的种子项目本身保持可运行状态，但不预先包含上述待开发功能。

## 安全边界

- 所有文件工具路径均经过 `Workspace.resolve` 规范化并限制在工作区内。
- `.env` 及其本地变体会被文件工具隐藏并拒绝访问，`.env.example` 只能包含占位值。
- 本地命令不会继承模型 API key 等凭据环境变量；直接读取 `.env` 的命令会被拒绝。
- Agent 启动的终端、Web 与桌面程序同样使用剥离凭据后的环境；Web 预览仅允许本机地址。
- 已知 API key 会在状态输出、命令结果、API 错误和会话日志边界统一脱敏。
- 已有文件不会被隐式覆盖。
- 文本替换必须唯一匹配。
- 命令执行具有超时和输出上限。
- 凭据和会话日志均被 Git 忽略。
- API 请求不使用 Code Interpreter、托管 Shell、Files API 或服务端文件搜索。

需要注意：Shell 命令仍以当前进程的操作系统权限运行，应用层的命令文本检查可能被间接
读取方式绕过。工作目录限制、凭据剥离和危险模式过滤不能替代真正的系统沙箱。处理不可信
项目时，应把密钥文件放在工作区外，并使用容器、虚拟机或低权限独立账户。详细说明见
[`SECURITY.md`](SECURITY.md)。

## 项目结构

```text
code-agent/
├─ code_agent/
│  ├─ agent.py          # 持续会话、Agent 回合循环与终止条件
│  ├─ llm.py            # OpenAI 兼容模型客户端
│  ├─ settings.py       # 公开配置解析与优先级
│  ├─ credentials.py    # 操作系统凭据库边界
│  ├─ events.py          # 与展示层无关的运行事件
│  ├─ service.py         # CLI/TUI 共享的运行时装配
│  ├─ tui/               # Textual 终端对话界面
│  ├─ context.py        # 上下文裁剪
│  ├─ conversation.py   # 可恢复会话快照与异常恢复
│  ├─ processes.py      # 可见应用启动、就绪检查与生命周期
│  ├─ approval.py       # 权限确认策略
│  ├─ session.py        # JSONL 事件日志
│  ├─ workspace.py      # 工作区路径边界
│  └─ tools/
│     ├─ registry.py    # 工具定义、校验与调度
│     ├─ files.py       # 文件工具
│     ├─ shell.py       # 前台命令工具
│     └─ process.py     # 终端、Web 与桌面程序展示工具
├─ tests/               # 无需 API key 的自动化测试
├─ examples/todo_app/   # 端到端演示种子项目
├─ docs/                # 架构说明
├─ README.txt           # 题目要求的简短提交说明
├─ SECURITY.md          # 安全边界
└─ pyproject.toml       # 安装和命令行入口
```

## 许可证

MIT License
