---
name: agent-traces-db
description: "Inspect, extract, and analyze PlayMoleculeAI agent conversation traces from the agent SQLite database (agent.db). Use whenever the task involves pulling raw conversation data, reconstructing turns, mining user prompts for evals, debugging tool failures from chat logs, or answering 'what did the agent do in conversation N', even when the user does not mention the database directly. In the dashboard codebase, an analytics DB and Python helpers layer on top, see the dashboard extras section."
---

# Working with the Agent Traces Database

Agent conversations are stored in a single SQLite database, `agent.db`. Every chat, message, tool call, reasoning trace, and edit lives here. Reading this database is the fastest way to answer questions like "what did the agent actually do", "which tool call failed and with what output", or "pull user prompts from these conversations for an eval".

This skill teaches you to read that DB directly with `sqlite3` and SQL. No wrappers, no helpers, no dashboard dependencies.

## Where the database lives

The canonical layout is `<data_root>/data/databases/<env>/agent.db` where `<env>` is typically `dev`, `prod`, or `open`. Exact `<data_root>` is machine-specific, if you don't know it, ask the user or `find <data_root> -name agent.db`.

Open the DB read-only so analysis can never corrupt the source:

```python
import sqlite3
conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
```

## Schema overview

Seven tables. `chats` and `messages` cover 95% of analysis tasks.

**`chats`**: one row per conversation.
Columns: `id` (int PK), `chat_uid` (hex string), `user_id`, `project`, `parent_id` (forked chats point at their source), `summary` (short title), `instructions` (full system prompt text), `created_at`, `deleted_at`.

**`messages`**: one row per conversational event.
Columns: `id`, `message_uid`, `chat_id`, `parent_id`, `response_id`, `item_index`, `item_data` (JSON payload, the real content), `created_at`, `rating`, `model`, `usage` (JSON), timing fields (`start_time`, `first_token_time`, `end_time`, `latency_ms`, `ttft_ms`, `tool_latency`), `status`.

**`edits`**: message edit history. `pre_edit_item_data` / `post_edit_item_data` are JSON.

**`jobs`**: PlayMolecule backend jobs linked to a chat (`chat_id`, `project`, `job_id`, `run_id`, `status`).

**`aiscientist`**: sandbox agent registrations tied to a chat.

**`users`**: per-user flags like `auto_accept`.

**`chatrequest`**: short-lived session tokens. Rarely useful for analysis.

## The ordering rule

Order `messages` by `id`:

```sql
ORDER BY id
```

`id` is an autoincrement primary key assigned by serialized inserts, so it strictly matches insertion order, which is the real conversational order. `created_at` has microsecond precision and agrees with `id`, so `ORDER BY created_at, id` is equivalent.

Do not wrap `created_at` in `datetime()`. SQLite's `datetime()` truncates to whole seconds and collapses parallel events (like a fan-out of 4 tool calls emitted in the same second) into a tie, at which point a secondary sort on `item_index` silently reorders them across different responses and you get a plausible but wrong sequence. `item_index` is only meaningful as a tiebreaker within a single `response_id`, not across the conversation.

## `item_data` is where the content lives

`item_data` is a JSON string. Parse with `json.loads`. Each row is one of:

- `message`: user or assistant text. Fields: `role`, `content` (string or list of text parts).
- `function_call`: the agent calling a tool. Fields: `name`, `call_id`, `arguments` (JSON string).
- `function_call_output`: the tool's reply. Fields: `call_id`, `output` (string or list of parts).
- `reasoning`: the model's internal reasoning summary. Fields: `summary` or `content`.
- `system_reminder`: context injected by the harness (viewer state, file listings, etc.).

One assistant turn can span many rows: reasoning entries, several `function_call`s in parallel, then a final `message`. Raw row count is not turn count.

## Choose the right unit

Match the unit to the task:

- **Raw rows**: exact payloads, timing, audit trail. `SELECT * FROM messages`.
- **Parsed items**: same rows, with `item_data` run through `json.loads`. Use this for almost all Python-side analysis.
- **Turns**: user-to-assistant exchanges rather than events. Collapse consecutive non-user items into the assistant half of a turn, start a new turn on each user `message`. Snippet below.
- **Prompts only**: eval mining. Filter `type == "message"` and `role == "user"`.

Starting at the wrong unit is the most common source of wasted work. Decide before you start querying.

## Read one conversation

```python
import sqlite3, json

conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, item_index, created_at, item_data, model, usage "
    "FROM messages WHERE chat_id = ? ORDER BY id",
    (chat_id,),
).fetchall()

for r in rows:
    item = json.loads(r["item_data"])
    t = item.get("type")
    if t == "message":
        role = item.get("role", "?")
        content = item.get("content")
        text = content if isinstance(content, str) else "".join(
            p.get("text", "") for p in (content or []) if isinstance(p, dict)
        )
        print(f"[{role}] {text}")
    elif t == "function_call":
        print(f"[call] {item['name']}({item.get('arguments','')})")
    elif t == "function_call_output":
        out = item.get("output")
        text = out if isinstance(out, str) else json.dumps(out)[:200]
        print(f"[out]  {text}")
    elif t == "reasoning":
        pass  # enable when debugging model thought
```

## Collapse rows into turns

```python
turns = []
current = {"user": None, "assistant_items": []}
for r in rows:
    item = json.loads(r["item_data"])
    if item.get("type") == "message" and item.get("role") == "user":
        if current["user"] is not None or current["assistant_items"]:
            turns.append(current)
        current = {"user": item, "assistant_items": []}
    else:
        current["assistant_items"].append(item)
turns.append(current)
```

Each turn is `{"user": <item>, "assistant_items": [reasoning/calls/outputs/message, ...]}`. The position of a turn in the list is a stable handle when pointing back at a specific exchange.

## Useful queries

Most recent conversations:

```sql
SELECT id, chat_uid, user_id, project, summary, created_at
FROM chats
WHERE deleted_at IS NULL
ORDER BY id DESC
LIMIT 20
```

Tool usage in a chat:

```sql
SELECT json_extract(item_data, '$.name') AS tool, COUNT(*) AS n
FROM messages
WHERE chat_id = ? AND json_extract(item_data, '$.type') = 'function_call'
GROUP BY tool
ORDER BY n DESC
```

Suspected tool failures (output text hints at an error):

```sql
SELECT id, created_at, item_data
FROM messages
WHERE chat_id = ?
  AND json_extract(item_data, '$.type') = 'function_call_output'
  AND (item_data LIKE '%Error%' OR item_data LIKE '%500%' OR item_data LIKE '%Traceback%')
ORDER BY id
```

Matching a tool call to its output uses `call_id`, which is carried on both the `function_call` and the `function_call_output`. Use it when you need to pair a specific call with its result.

## Export a chat for external analysis

When handing a conversation off to another tool (an eval harness, a notebook, a reviewer), dump it to JSONL with `item_data` and `usage` pre-parsed so downstream code skips the string/JSON round trip:

```python
with open(out_path, "w") as f:
    f.write(json.dumps({"_chat": dict(chat_row)}, default=str) + "\n")
    for r in rows:
        d = dict(r)
        d["item_data"] = json.loads(d["item_data"])
        if d.get("usage"):
            d["usage"] = json.loads(d["usage"])
        f.write(json.dumps(d, default=str) + "\n")
```

First line is the `chats` row, subsequent lines are messages in conversational order.

## Practical notes

`instructions` on `chats` is the system prompt at conversation start. It can be very large, ignore it unless you're auditing prompt changes.

`system_reminder` items are not noise. Viewer state, file listings, and other real-time harness context live here and often explain why the agent chose what it did.

For eval mining, keep `chat_id`, the message `id`, and `created_at` alongside any prompt you extract. Identical user text can refer to very different viewer or project state.

Prefer SQL aggregates (`COUNT`, `GROUP BY`, `json_extract`) when you only need counts or shapes. Materialize rows in Python only when you need to parse `item_data` further.

## Dashboard codebase extras

The skill is also used inside the PlayMolecule dashboard repo. There, `agent.db` is not the whole picture:

- A second SQLite database holds precomputed facts (`chat_facts`, `turn_facts`, `tool_facts`) and trace-level labels (`trace_tag_*`, `trace_filter_labels`). These let you filter or discover conversations by size, cost, tool usage, or domain tag before drilling into raw messages.
- Python helpers in `backend/data/` and `backend/agents/` wrap connection handling, turn construction, and tag queries so you rarely need to write the SQL yourself.

Detect the dashboard context by checking for `backend/data/store.py` or `backend/agents/trace_tagger.py` in the project root. When those exist, read `references/dashboard-extras.md` for the analytics schema, helper inventory, and the common workflows (tagged trace extraction, prompt mining at scale, context reconstruction around a candidate turn). The raw-DB recipes above still apply, the extras save work when the dashboard layer is available.
