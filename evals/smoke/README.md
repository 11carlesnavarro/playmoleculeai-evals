# smoke

One case: pmai writes a file, and the tests check the file, the answer and that no tool call failed. Run it after a change to the image or the agent, to see that a run works at all (gpt-6-luna).

```bash
make run                          # the default job: evals/smoke/hello-file.yaml
```

Status: no smoke run with a reward is seen yet (the first one, on 2026-10-05, stopped before the tests on causes that are now fixed).
