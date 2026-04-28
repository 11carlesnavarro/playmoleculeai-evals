---
name: issue
description: Log an issue as a markdown file at docs/issues/{kebab-case-slug}.md in the current project. Use whenever the user wants to record a bug, problem, idea, or follow-up task to address later, including phrases like "log this as an issue", "add an issue for X", "track this", "this is an issue", "open an issue about ...", or "/issue ...". Capture the title and enough context that a future solution attempt has what it needs.
---

# issue

Write a markdown file at `docs/issues/{slug}.md` describing what the user reported.

## What to write

Start with a short H1 title, then a description containing enough detail to inform a later solution: what is wrong or wanted, where it shows up (file, component, page, command), any reproduction or symptom details the user mentioned, and any constraints or hints they have given. Pull relevant context from the surrounding conversation if the user is referring to something just discussed.

There is no fixed template. Write it as prose unless the content is naturally a list. Do not invent sections, severity levels, or acceptance criteria the user did not bring up. Gaps are fine. The goal is faithfully recording the issue, not dressing it up.

## Filename

Kebab-case slug derived from the title: lowercase, ASCII letters and digits, `-` between words, no leading or trailing dashes. Drop filler words like "the" or "a" only when it tightens the slug without losing meaning.

If `docs/issues/{slug}.md` already exists, suffix `-2`, `-3`, etc. until the path is free rather than overwriting, and tell the user which filename you used.

## Path

`docs/issues/` is relative to the current working directory. Create the directory if it does not exist.

## After writing

Reply with one short line stating the path of the file you wrote. Do not echo the body back to the user.
