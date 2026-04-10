# Critique — grade the grader

You are auditing an evaluation set after it ran against multiple models.
Your job is to flag assertions and rubric dimensions that are *not
discriminating*.

A non-discriminating assertion either passes for every model (so it never
catches a regression) or fails for every model (so it's likely buggy or
misaligned with the prompt).

## Per-assertion pass rates

{assertion_table}

## Per-dimension score distribution

{rubric_table}

## Output format

Return only valid JSON:

```json
{{
  "non_discriminating": [
    {{
      "assertion_or_dimension": "<id>",
      "reason": "passes for all 5 models / fails for all 5 models / ...",
      "suggestion": "<concrete fix: tighten threshold, replace with X, remove>"
    }}
  ],
  "summary": "<one paragraph for the human reviewer>"
}}
```
