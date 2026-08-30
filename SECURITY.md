# Security policy

## Credentials

Pass credentials through environment variables or the locally ignored `.env` file. The
built-in parser accepts only `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_BASE_URL`, and never
overwrites existing process variables. Never commit `.env` files or include keys in
screenshots, recordings, session logs, bug reports, or command history. If a key is ever
committed or recorded, revoke it immediately and create a replacement.

The built-in file listing, search, read, write, and edit paths hide or reject `.env` credential
files. `.env.example` remains visible because it must contain placeholders only. Shell commands
are a separate trust boundary and may still access files available to the operating-system user;
review command approvals carefully.

## Local execution

Code Agent can modify files and run commands with the privileges of its process. Workspace
checks constrain the built-in file tools but do not create an operating-system sandbox for
shell commands. Use `suggest` mode when reviewing every mutation, and run unfamiliar tasks in
a disposable checkout, container, or virtual machine.

The destructive-command filter blocks common high-impact patterns. It cannot understand every
shell program or indirect side effect, so it must not be treated as a complete security
boundary.

## Reporting

Do not publish a report containing a working credential or private source code. Describe the
smallest reproducible case and the relevant termination status or redacted JSONL events.
