# Status and next steps

The first plan (phases 0 to 7, with the checks of each phase) is in git history: this file at commit 4a84255.

## Status (2026-10-15)

- Harbor runs `pmai run` in Docker, one container per case; viewer cases get a PMView sidecar (headless Chromium).
- `evals/smoke`: one case. No smoke run with a reward is seen yet.
- `evals/viewer-quality`: 20 cases (15 train, 5 held out). Ten hill climb rounds took the mean review score from
  5.93 to 9.20 (round 9). Round 10 ran on 2026-10-15 and is not reviewed. The code is on the `viewer-quality`
  branches of playmoleculeAI, acellera-skills and pmview, on one machine only (not pushed).
- Human review: `make review`. The judge (`judge.py`, gpt-6.1-sol) agrees with the reviews on 77% of the rubric
  lines of the 145 reviewed trials, and does not rank the rounds as the reviews do: not usable as the score yet.

## Next steps

1. **The repo for colleagues.** Done: production defaults in the Makefile and `local.mk` for other checkouts, the
   README Setup and "Add an eval", checks of the cases and the image pins in `make test`, working notes out of git,
   the reviewer in new ratings, a code review (a judge or a test file that fails is an infra error, not a 0).
   Open: push the three `viewer-quality` branches, so that others can build the current version; a smoke run with
   a reward in Docker; the sandbox image user (`[verify]` in `docker/eval/Dockerfile`).
2. **Try changes by hand, with the local frontend and pmai.** Possible ways (not decided):
   - the eval sidecar, as now: `make viewer` with a PMView build and one `pmai run --viewer-id` a turn (works now,
     no chat panel);
   - PMView with `npm run dev` against the deployed backend (PMView changes only);
   - new: a Vite proxy rule that sends the agent websocket to a local `pmai serve`, and `pmai run --viewer-id
     <the tab's session id>`; the chat panel also needs the backend's rollout routes.
3. **Rubrics and the judge.** Make the judge agree with the reviews: the prompt (it reads some lines too literally),
   the rubric lines that it cannot see (for example "top-scoring" with no score in the image), then a second pass
   on the 145 reviewed trials for self-consistency. The review notes find quality differences that the rubric does
   not: atoms too big, labels nobody asked for, the camera angle, context too strong, colours. Add them as rubric
   lines, or compare two views of the same case (A/B).
4. **Final runs.** The first version (production PMAI, skills and PMView) against the current one, with gpt-6-luna
   and gpt-6.1-sol at different reasoning efforts, on all 20 cases. Graded by the judge of step 3.
5. **A dashboard.** Only if `make view` (Harbor's viewer) is not good enough for step 4.

## Later

- PlayMolecule job tasks: pmai waits for its jobs (`--wait-jobs`), the trial mounts the eval bucket.
- Scale out: a nightly job, more trials in parallel (for example on Modal), a separate verifier container.

## Risks

| Risk | Action |
|---|---|
| The provider keys are in the trial container, and the agent's bash can read them. | Eval only keys. |
| The sandbox image user is not root (`[verify]` in `docker/eval/Dockerfile`). | Restore its `USER`. |
| PMView changes under us. | Use a PMView build or production, not the dev site (a Vite dev server). |
| OpenAI stops some prompts as biological risk. | A job file runs a stopped trial once more. |
| Harbor 0.x changes fast. | Keep `harbor==0.24.0`; read the changelog before an upgrade. |
