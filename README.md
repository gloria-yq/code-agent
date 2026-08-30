# Code Agent：从零实现的编程智能体

Code Agent 是一个小型、透明、便于理解的命令行编程智能体。用户给出编程任务后，它会调用兼容 OpenAI Chat Completions 协议的大语言模型，让模型根据本地工具的执行结果持续决策，直到完成任务或触发明确的停止条件。

本项目**未使用任何 Agent 框架或 Agent SDK**。模型客户端、对话历史、工具定义、参数校验、本地执行、上下文裁剪、权限确认、事件日志、错误处理和循环终止均在本仓库中自行实现。运行时代码只依赖 Python 标准库。

## 主要功能

- 使用 `list_files` 浏览工作区目录。
- 使用 `search_text` 搜索 UTF-8 文本并返回文件名和行号。
- 使用 `read_file` 按行读取文件。
- 使用 `write_file` 创建文件或显式覆盖已有文件。
- 使用 `edit_file` 执行唯一文本块替换，避免误改多处内容。
- 使用 `run_command` 在本地执行测试、构建及其他命令。
- 将每次工具结果返回模型，使模型能够继续分析、纠错和验证。
- 对文件路径进行规范化，禁止文件工具访问指定工作区之外的位置。
- 支持三种权限模式，控制文件修改和命令执行是否需要人工确认。
- 拦截常见破坏性命令，并限制命令执行时间与输出长度。
- 在模型异常、连续工具错误、重复调用、达到轮次上限或用户中断时停止。
- 对超长工具输出和旧对话进行本地裁剪，控制模型请求上下文大小。
- 将运行过程记录为追加写入的 JSONL 事件日志，便于调试和复盘。

## 系统架构

```text
用户任务
   |
   v
Agent 主循环 ------> 上下文管理 ------> OpenAI 兼容模型接口
   ^                                      |
   |                                      | 文本或工具调用
   |                                      v
   +---- 工具结果 <---- 权限策略 <---- 工具注册表
                                     /          \
                                  文件工具     命令工具
                                     |          |
                                     +-- 工作区边界 --+
```

一次“轮次”对应一次模型请求。若模型返回工具调用，主循环会依次完成以下操作：

1. 保存模型返回的 assistant 消息；
2. 解析工具参数 JSON；
3. 校验必填字段、额外字段和基础数据类型；
4. 执行权限策略；
5. 在本地调用对应工具；
6. 将成功结果或结构化错误作为 `tool` 消息写回历史；
7. 携带更新后的历史进入下一轮。

当模型不再请求工具并返回非空最终文本时，任务正常结束。更加详细的设计约束见 [`docs/architecture.md`](docs/architecture.md)。

## 环境要求

- Python 3.10 或更高版本
- 支持 OpenAI Chat Completions tool calling 协议的模型服务
- 对应模型服务的 API key

运行时不需要安装第三方 Python 依赖。

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

也可以将 `.env.example` 复制为待处理工作区中的 `.env`，然后在本地填写：

```text
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=模型名称
```

程序只读取上述三个白名单配置项，且系统环境变量优先于 `.env`。`.env` 已被 Git 忽略，文件工具也会主动隐藏并拒绝读取该文件。真实密钥不得提交到仓库、写入文档或出现在公开日志中。

如使用其他 OpenAI 兼容服务，请修改 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`。基础地址应指向服务的 `/v1` 根路径，程序会自动追加 `/chat/completions`。

## 运行方法

让 Agent 处理当前目录：

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
--max-turns N
--approval-mode {suggest,auto-edit,full}
--no-session-log
```

## 权限模式

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

在工作区目录中执行前台命令，返回退出码、标准输出和标准错误。命令具有超时及输出上限，常见破坏性模式会被直接拒绝。

## 循环终止条件

| 状态 | 含义 |
| --- | --- |
| `completed` | 模型返回非空最终文本，且没有继续调用工具。 |
| `model_error` | 模型 API 请求或响应解析发生不可恢复错误。 |
| `protocol_error` | 模型既未返回文本，也未返回工具调用。 |
| `tool_error_limit` | 工具连续失败达到设定上限。 |
| `stalled` | 模型连续三轮提出相同的工具请求。 |
| `max_turns` | 达到配置的最大轮次数。 |
| `invalid_task` | 用户任务为空。 |

用户按下 Ctrl+C 时，CLI 会立即取消并以退出码 130 结束。

## 上下文管理

Agent 在内存中保留本次任务的完整消息历史，并通过 JSONL 记录关键事件。每次请求模型之前，上下文管理器会：

1. 深拷贝当前消息，避免裁剪过程修改原始历史；
2. 截断过长的工具输出；
3. 估算序列化消息的字符数；
4. 始终保留系统提示和原始用户任务；
5. 尽可能保留近期完整消息；
6. 插入明确的历史省略提示。

当前实现使用字符预算而不是模型专用 tokenizer，以保持逻辑透明并兼容不同服务。其不足是 token 估算不如专用 tokenizer 精确。

## 错误处理与日志

- API 限流、超时和部分服务器错误会进行有限次数的指数退避重试。
- 工具参数错误不会导致主进程崩溃，而会作为结构化结果返回模型纠正。
- 每次模型请求、响应、工具调用、工具结果和最终状态都会写入 JSONL 事件。
- 默认日志目录为工作区中的 `.code-agent/sessions/`，该目录不会提交到 Git。
- 日志不会记录 API key，但任务内容、工具参数和工具输出可能包含项目数据，不应公开分享未经检查的日志。

## 测试

测试使用 Python 内置的 `unittest` 和模拟模型客户端，不需要 API key 或网络访问：

```bash
python -m unittest discover -v
```

测试覆盖：

- 模型—工具—模型完整往返；
- 正常完成、重复调用、最大轮次和工具错误上限；
- 工具参数 JSON 解析及基础类型校验；
- 文件创建、读取、唯一替换和文本搜索；
- 工作区路径逃逸攻击；
- `.env` 隐藏和拒绝读取；
- 命令执行及破坏性命令拒绝；
- 上下文裁剪且不修改原始消息；
- JSONL 事件日志；
- Chat Completions 请求载荷和返回解析；
- `.env` 白名单加载及环境变量优先级。

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
- 已有文件不会被隐式覆盖。
- 文本替换必须唯一匹配。
- 命令执行具有超时和输出上限。
- 凭据和会话日志均被 Git 忽略。
- API 请求不使用 Code Interpreter、托管 Shell、Files API 或服务端文件搜索。

需要注意：Shell 命令以当前进程的操作系统权限运行。工作目录限制和危险模式过滤不能替代真正的系统沙箱。详细说明见 [`SECURITY.md`](SECURITY.md)。

## 项目结构

```text
code-agent/
├─ code_agent/
│  ├─ agent.py          # Agent 主循环与终止条件
│  ├─ llm.py            # OpenAI 兼容模型客户端
│  ├─ context.py        # 上下文裁剪
│  ├─ approval.py       # 权限确认策略
│  ├─ session.py        # JSONL 事件日志
│  ├─ workspace.py      # 工作区路径边界
│  └─ tools/
│     ├─ registry.py    # 工具定义、校验与调度
│     ├─ files.py       # 文件工具
│     └─ shell.py       # 命令工具
├─ tests/               # 无需 API key 的自动化测试
├─ examples/todo_app/   # 端到端演示种子项目
├─ docs/                # 架构说明
├─ README.txt           # 题目要求的简短提交说明
├─ SECURITY.md          # 安全边界
└─ pyproject.toml       # 安装和命令行入口
```

## 许可证

MIT License
