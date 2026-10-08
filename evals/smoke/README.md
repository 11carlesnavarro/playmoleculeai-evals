# smoke

One case: pmai writes a file, and a test checks it (plus a judge test, if `ANTHROPIC_API_KEY` is set). Run it after a change to the image or the agent, to see that a run works at all.

```bash
make run                          # the default job: evals/smoke/hello-file.yaml
```
