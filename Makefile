SANDBOX ?= europe-southwest1-docker.pkg.dev/repositories-368911/acellera-docker-apps/pm-python-sandbox:latest
PMAI ?= ../playmoleculeAI
SKILLS ?= ../../acellera/acellera-skills
# skills baked in the image: a git ref, as production (main), not the working tree
SKILLS_REF ?= main
JOB ?= evals/smoke/hello-file.yaml
# CASE=<case> runs one case of the job (acellera-bench: CASE=<set>/<case>)
CASE ?=
# a new results/<eval>-<job file>[-<case>]-<date>/ per run; NAME=<an old one> resumes it (Harbor keeps its finished trials)
NAME ?= $(notdir $(patsubst %/,%,$(dir $(JOB))))-$(basename $(notdir $(JOB)))$(if $(CASE),-$(notdir $(CASE)))-$(shell date +%Y%m%d-%H%M%S)

.PHONY: image viewer run watch view test lint

# sdist first, then the wheel from it: a direct wheel build reuses $(PMAI)/build/lib,
# which keeps files deleted from src
image:  ## pmai-eval:latest = sandbox image + pmai + grader + skills
	rm -rf dist && (cd $(PMAI) && uv build -o $(CURDIR)/dist) && rm dist/*.tar.gz
	git -C $(SKILLS) archive $(SKILLS_REF) skills | tar -x -C dist
	echo "skills: $(SKILLS_REF) $$(git -C $(SKILLS) log -1 --format='%h %ad %s' --date=short $(SKILLS_REF))"
	docker build -t pmai-eval:latest --build-arg SANDBOX=$(SANDBOX) -f docker/eval/Dockerfile .

viewer:  ## pmai-viewer:latest = headless Chromium + docker/viewer/server.py (PMView comes from the site)
	docker build -t pmai-viewer:latest -f docker/viewer/Dockerfile .

run:  ## make run JOB=evals/<eval>/<job>.yaml [CASE=<case>]
	set -a && . ./.env && set +a && HARBOR_TELEMETRY=off uv run harbor run -c $(JOB) --job-name $(NAME) --jobs-dir results \
	  $(if $(CASE),-p $(dir $(JOB))cases/$(CASE))

watch:  ## follow the newest job as it runs (in a second shell); make watch JOB=results/<job> for another
	uv run python scripts/watch.py $(if $(filter results/%,$(JOB)),$(JOB))

view:
	HARBOR_TELEMETRY=off uv run harbor view results

test:
	uv run pytest -q

lint:
	uv run ruff check src tests evals scripts docker
