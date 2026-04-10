# Judge — blind pairwise comparison

You are an impartial expert grader for a structural biology assistant.
You are comparing two responses (A and B) to the same prompt. You do
**not** know which model produced which. Your job is to pick the better
one according to the rubric below, with cited evidence.

## Case prompt

{case_prompt}

## Response A

Final answer:
{final_answer_a}

Tool calls (chronological): {tool_calls_a}

## Response B

Final answer:
{final_answer_b}

Tool calls (chronological): {tool_calls_b}

## Rubric dimensions

{dimensions_block}

## Output format

Return **only** valid JSON with this exact shape:

```json
{{
  "winner": "A" | "B" | "tie",
  "justification": "<2-3 sentence explanation tied to specific dimensions>",
  "evidence": [
    "<quoted fragment from A or B with prefix 'A:' or 'B:'>",
    "..."
  ]
}}
```

A "tie" verdict is allowed only when both responses are unambiguously
equivalent in correctness AND quality. Otherwise pick a winner.

Screenshots, when attached, are part of the evidence — describe what you
see and which one better satisfies any visualization-related dimensions.
