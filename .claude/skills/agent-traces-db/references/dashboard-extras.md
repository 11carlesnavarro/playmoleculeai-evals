# Dashboard Codebase Extras

This reference applies only inside the PlayMolecule dashboard repo, which layers an analytics database and a set of Python helpers on top of the raw `agent.db` covered in `SKILL.md`. If the current project has no `backend/data/store.py` or `backend/agents/trace_tagger.py`, stop here and use the raw-DB recipes from `SKILL.md` directly.

## The analytics database

Alongside the source `agent.db`, the dashboard maintains a second SQLite file at `.cache/dashboard-<env>-facts.sqlite3` with derived data. Nothing in this file is authoritative: it's rebuilt from the source DB and can be refreshed when you suspect it's stale.

Precomputed facts:

- `chat_facts`: per-conversation metrics (`turn_count`, `cost_usd`, `primary_model`, `last_activity_at`, project, user).
- `turn_facts`: per-turn metrics inside a conversation.
- `tool_facts`: per-tool-call stats (`tool_name`, `is_error`, latency, chat and turn keys).

Trace labeling:

- `trace_tag_traces`: one row per tagged trace. A trace is a contiguous range of user turns in a conversation, keyed by `(chat_id, trace_index)` with `start_user_index` and `end_user_index`.
- `trace_tag_trace_tags`: maps `(chat_id, trace_index)` to one or more `tag_id`s (e.g. `molecular-visualization`, `docking`).
- `trace_tag_message_traces`: maps `message_id` to the trace it belongs to, plus `user_message_id` and `user_index` handles.
- `trace_filter_labels`: per-chat filter status (`retained`, `discarded`, etc.). Most analysis should filter where `COALESCE(status, 'retained') = 'retained'`.

## Python helpers

All helpers live under `backend/` in the dashboard repo.

Raw source DB:

```python
from data.loader import _get_db_connection, DB_PATH, load_conversation_rows_from_db

conn = _get_db_connection(DB_PATH)  # read-only, row_factory preset
rows, error = load_conversation_rows_from_db(chat_id, include_lineage=False)
```

`DB_PATH` is resolved in `backend/data/db_paths.py` from `AGENT_DB_PATH`, then `AGENT_DB_ENV`, then the default layout `<repo_root>/data/databases/<env>/agent.db`.

Analytics DB + trace tags:

```python
from data.store import DashboardReadStore

store = DashboardReadStore()  # or DashboardReadStore(source_db_path=..., analytics_db_path=...)
store.refresh()  # call if you suspect the analytics view is stale

with store._analytics_connection() as conn:
    ...  # arbitrary SQL against the analytics DB

tag_data = store.get_trace_tags(chat_id)       # trace metadata + messageTraces mapping
result  = store.get_trace_filter_result(chat_id)
targets = store.list_trace_tag_targets()       # all chats that carry any tag
```

Turn construction:

```python
from agents.trace_tagger import build_trace_turns, format_trace_turns

turns = build_trace_turns(rows)
print(format_trace_turns(turns))
```

`build_trace_turns` is the same collapsing that the tagging pipeline uses. It merges consecutive assistant rows into one turn and skips non-conversational rows such as system reminders. Prefer it over reimplementing the collapsing yourself when you're in the dashboard repo.

## Workflow: inspect one conversation

```python
from data.loader import load_conversation_rows_from_db
from agents.trace_tagger import build_trace_turns, format_trace_turns

rows, error = load_conversation_rows_from_db(chat_id, include_lineage=False)
turns = build_trace_turns(rows)
print(format_trace_turns(turns))
```

## Workflow: extract traces by tag

Tags live on traces, not on isolated messages. A tagged trace is a contiguous user-turn range inside a conversation.

```python
from data.store import DashboardReadStore

store = DashboardReadStore()
store.refresh()
tag_id = "molecular-visualization"

with store._analytics_connection() as conn:
    trace_rows = conn.execute(
        """
        SELECT t.chat_id, t.trace_index, t.start_user_index, t.end_user_index,
               t.summary, t.confidence
        FROM trace_tag_traces t
        JOIN trace_tag_trace_tags tt
          ON tt.chat_id = t.chat_id AND tt.trace_index = t.trace_index
        LEFT JOIN trace_filter_labels f ON f.chat_id = t.chat_id
        WHERE tt.tag_id = ?
          AND COALESCE(f.status, 'retained') = 'retained'
        ORDER BY t.chat_id, t.trace_index
        """,
        (tag_id,),
    ).fetchall()
```

Load the conversation and slice the turn range:

```python
from data.loader import load_conversation_rows_from_db
from agents.trace_tagger import build_trace_turns

for row in trace_rows:
    raw_rows, error = load_conversation_rows_from_db(row["chat_id"], include_lineage=False)
    if error:
        continue
    turns = build_trace_turns(raw_rows)
    trace_turns = turns[row["start_user_index"] - 1 : row["end_user_index"]]
```

This is the right path when you want to inspect a moderate number of traces by hand.

## Workflow: mine prompts from tagged traces at scale

For larger jobs, start from `trace_tag_message_traces`. It already maps message ids to trace ids and user-turn indices, so you don't have to rebuild every conversation just to find candidate prompts.

```python
with store._analytics_connection() as conn:
    rows = conn.execute(
        """
        SELECT DISTINCT
            mt.chat_id, mt.trace_index, mt.user_index, mt.user_message_id,
            t.start_user_index, t.end_user_index, t.summary, t.confidence
        FROM trace_tag_message_traces mt
        JOIN trace_tag_traces t
          ON t.chat_id = mt.chat_id AND t.trace_index = mt.trace_index
        JOIN trace_tag_trace_tags tt
          ON tt.chat_id = mt.chat_id AND tt.trace_index = mt.trace_index
        LEFT JOIN trace_filter_labels f ON f.chat_id = mt.chat_id
        WHERE tt.tag_id = ?
          AND COALESCE(f.status, 'retained') = 'retained'
          AND mt.message_id = mt.user_message_id
        ORDER BY mt.user_message_id
        """,
        (tag_id,),
    ).fetchall()
```

Then fetch only those source messages from `agent.db`. Much faster than rebuilding every tagged conversation up front.

Keep the full trace handle alongside each prompt: `env`, `chat_id`, `trace_index`, `user_index`, `user_message_id`. That makes later context reconstruction straightforward.

## Workflow: reconstruct context for a candidate

Once you have a candidate prompt, the next question is usually "what was the user referring to". Recover the full trace, and when useful a smaller local window around the candidate turn:

```python
from data.loader import load_conversation_rows_from_db
from agents.trace_tagger import build_trace_turns

chat_id     = candidate["chat_id"]
trace_index = candidate["trace_index"]
user_index  = candidate["user_index"]

tag_data   = store.get_trace_tags(chat_id)
trace_meta = next(t for t in tag_data["traces"] if t["traceIndex"] == trace_index)

rows, error = load_conversation_rows_from_db(chat_id, include_lineage=False)
turns = build_trace_turns(rows)

trace_turns  = turns[trace_meta["startUserIndex"] - 1 : trace_meta["endUserIndex"]]
window_start = max(0, user_index - 3)
window_end   = min(len(turns), user_index + 2)
local_turns  = turns[window_start:window_end]
```

The local window is enough for most review tasks. When it isn't, the full tagged trace is the next step. You only need the full conversation when the relevant state predates the tagged trace.

## Workflow: aggregate facts to narrow the search

Use the analytics tables to filter before reading raw content:

```sql
SELECT chat_id, turn_count, cost_usd, primary_model
FROM chat_facts
WHERE turn_count > 20
ORDER BY last_activity_at DESC;

SELECT tool_name, COUNT(*) AS calls, SUM(is_error) AS errors
FROM tool_facts
WHERE chat_id = ?
GROUP BY tool_name;
```

These are the right entry point when you want to pick conversations by size, project, model, or tool usage before reading the underlying trace.

## Practical notes

Don't treat embedded viewer state or file references in a user message as noise. For eval mining they're often what makes a prompt reproducible.

If you deduplicate prompts, keep enough metadata to recover the original context later. Identical text can refer to different structures or different viewer states.

For small investigations, clarity matters more than speed. For large extractions, query ids from the analytics database first and fetch only the source rows you actually need.
