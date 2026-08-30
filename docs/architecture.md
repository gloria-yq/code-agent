# Architecture and invariants

## Control loop

`CodingAgent.run` owns the only agent loop. It starts with one system message and one user
message. Each iteration derives a bounded API view of the local history, requests a model
response, and appends the assistant message to the canonical in-memory history.

If the assistant returns tool calls, the loop processes them in order. For every call it:

1. parses JSON arguments;
2. validates required, extra, and primitive-typed fields;
3. applies the human approval policy;
4. dispatches the local handler;
5. serializes either the result or a structured error into a matching tool message.

If the assistant returns text without calls, that text is the final response. The loop never
uses a hosted execution tool and never treats unstructured assistant text as a shell command.

## Invariants

- The first two canonical messages are the system prompt and original user task.
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

Ctrl+C is handled at the CLI boundary and exits with code 130.

## Context policy

The canonical history is kept locally for the current run and the event trail remains
append-only. Before an API request, `ContextManager`:

1. bounds each large tool message;
2. estimates request size in serialized characters;
3. preserves the system prompt and original task;
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
