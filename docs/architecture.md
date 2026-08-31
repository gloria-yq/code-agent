# Architecture and invariants

## Control loop

The CLI owns an outer interaction loop and `CodingAgent.run` owns one inner ReAct loop per
user input. `CodingAgent` retains the canonical message list between calls, so a follow-up is
appended after the preceding assistant and tool messages instead of starting a new context.
Each model iteration derives a bounded API view of that shared history, requests a response,
and appends the assistant message to the canonical in-memory conversation.

If the assistant returns tool calls, the loop processes them in order. For every call it:

1. parses JSON arguments;
2. validates required, extra, and primitive-typed fields;
3. applies the human approval policy;
4. dispatches the local handler;
5. serializes either the result or a structured error into a matching tool message.

If the assistant returns text without calls, that text is the final response. The loop never
uses a hosted execution tool and never treats unstructured assistant text as a shell command.

## Invariants

- The first canonical message is the system prompt; subsequent user turns share one history.
- Slash commands are routed by the CLI and never enter the model-visible conversation.
- A local tool result always carries the originating `tool_call_id`.
- Unknown tools and invalid arguments become model-visible errors instead of process crashes.
- Tool arguments are validated locally instead of depending on provider-specific strict schemas.
- Tool handlers return JSON objects, keeping the model-facing protocol predictable.
- Filesystem paths are resolved through a single workspace boundary object.
- Existing files are never overwritten implicitly.
- An exact edit succeeds only when its old block occurs once.
- The command executor always has a timeout and output limit.
- Context preparation deep-copies messages; compaction does not rewrite the event trail.
- Credentials are read once from environment variables and never written to a session event.
- File tools hide and reject credential `.env` files even when the model requests them directly.
- An interrupted user turn is rolled back to its starting message boundary, so partial tool-call
  sequences cannot corrupt the next request.

## Termination

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
| `interrupted` | Ctrl+C interrupted a user turn and its partial messages were rolled back. |

In interactive mode, a completed turn returns control to the prompt instead of terminating the
process. `/new` resets the canonical messages to the system prompt. Ctrl+C during model/tool work
returns an `interrupted` result; one-shot mode maps that result to exit code 130.

## Context policy

The canonical history is kept locally for the current interactive session and the event trail remains
append-only. Before an API request, `ContextManager`:

1. bounds each large tool message;
2. estimates request size in serialized characters;
3. preserves the system prompt and the oldest conversation anchor;
4. keeps as much recent history as fits;
5. adds an explicit omission notice.

Character counting is deliberately transparent and provider-independent, but less accurate
than a model-specific tokenizer. A production extension could add tokenizer adapters without
changing the loop contract.

## Trust boundaries

The API is trusted to propose actions, not to execute them. The registry validates model
output before any handler runs. The workspace boundary protects file tools. Approval policy
mediates mutation categories. Shell pattern filtering provides a final local rejection layer.

The command tool is not a complete sandbox: a permitted shell command can still access data
available to the current operating-system user. For high-risk or untrusted tasks, run Code
Agent inside a container or disposable virtual machine.
