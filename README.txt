项目地址：https://github.com/gloria-yq/code-agent

运行环境：Python 3.10 及以上。克隆仓库后执行“python -m pip install -e .”。进入待处理项目后运行“code-agent --workspace .”启动 TUI；首次使用可在 /connect 中测试并配置 OpenAI 或 DeepSeek，API key 保存到操作系统凭据库，不进入项目或用户配置文件。也可使用环境变量或工作区外的 env 文件。传入“code-agent \"任务\"”执行单次任务，“--classic”启动经典命令行会话。

本项目未使用任何 Agent 框架或 Agent SDK，也不依赖服务端文件或代码执行工具。模型客户端、持续对话历史、工具定义、参数校验、文件与命令本地执行、循环控制、上下文裁剪、错误恢复和 JSONL 会话记录均自行实现。Textual 只用于终端展示，keyring/platformdirs 只用于本地配置与凭据存储。

安全方面，所有文件路径必须位于指定工作区；覆盖已有文件须显式声明；文本替换必须唯一匹配；命令具有超时和输出上限，并拒绝常见破坏性命令。Agent 在模型异常、连续工具错误、重复调用、达到轮次上限或用户中断时均会明确停止。仓库提供无需 API key 的单元测试与设计说明。
