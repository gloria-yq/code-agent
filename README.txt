项目地址：https://github.com/gloria-yq/code-agent

运行环境：Python 3.10 及以上。克隆仓库后执行“python -m pip install -e .”。通过系统环境变量或未入库的 .env 配置 OpenAI 或 DeepSeek；真实密钥不得进入版本控制。进入待处理项目后运行“code-agent --workspace .”启动持续对话，可追问、纠正和追加任务；传入“code-agent \"任务\"”则执行单次任务。可用 --approval-mode suggest、auto-edit 或 full 调整人工确认范围。

本项目未使用任何 Agent 框架或 Agent SDK，运行时也不依赖服务端文件、代码执行工具。模型客户端、持续对话历史、工具定义、参数校验、文件与命令本地执行、双层循环控制、上下文裁剪、错误恢复和 JSONL 会话记录均自行实现。Agent 支持 OpenAI 兼容接口及 DeepSeek 思考模式，可浏览和读取文件、创建文件、唯一文本块编辑、执行带超时的测试命令，并把结果返回模型继续决策。

安全方面，所有文件路径必须位于指定工作区；覆盖已有文件须显式声明；文本替换必须唯一匹配；命令具有超时和输出上限，并拒绝常见破坏性命令。Agent 在模型异常、连续工具错误、重复调用、达到轮次上限或用户中断时均会明确停止。仓库提供无需 API key 的单元测试与设计说明。
