SANDBOX ?= europe-southwest1-docker.pkg.dev/repositories-368911/acellera-docker-apps/pm-python-sandbox:latest
# the checkouts that the images come from (see the README, Setup); set others in local.mk (not in git)
PMAI ?= ../playmoleculeAI
SKILLS ?= ../acellera-skills
# skills baked in the image: a git ref, or empty = the working tree with its changes
SKILLS_REF ?= main
# PMView in pmai-viewer: the build/ of a playmolecule-viewer checkout (npm run build there first),
# or empty = the PMView of the site that the sidecar opens
PMVIEW ?=
-include local.mk
# git refuses a checkout that belongs to another user (a shared disk) without this
GIT = git -c safe.directory='*'
# $(call rev,<checkout>[,<ref>]): "<commit> <subject> (<n> changed files)" for the build log
rev = $$($(GIT) -C $(1) log -1 --format='%h %s' $(2)) ($$($(GIT) -C $(1) status --short | wc -l) changed files)
JOB ?= evals/smoke/hello-file.yaml
# CASE=<case> runs one case of the job
CASE ?=
# make view and make review: the port you tunnel (one at a time on one port)
PORT ?= 8080
# a new results/<eval>-<job file>[-<case>]-<date>/ per run; NAME=<an old one> resumes it (Harbor keeps its finished trials)
NAME ?= $(notdir $(patsubst %/,%,$(dir $(JOB))))-$(basename $(notdir $(JOB)))$(if $(CASE),-$(notdir $(CASE)))-$(shell date +%Y%m%d-%H%M%S)

.PHONY: help image viewer run watch view review test lint

help:  ## this list
	@awk -F':.*## ' '/^[a-z]+:.*##/ {printf "%-7s %s\n", $$1, $$2}' Makefile
	@echo "Settings (make <target> VAR=value, or in local.mk): JOB CASE PORT NAME PMAI SKILLS SKILLS_REF PMVIEW"

# sdist first, then the wheel from it: a direct wheel build reuses $(PMAI)/build/lib,
# which keeps files deleted from src
image:  ## pmai-eval:latest = sandbox image + pmai + grader + skills
	@test -d $(PMAI) -a -d $(SKILLS) || { echo "No checkout at $(PMAI) or $(SKILLS): see the README, Setup (or set them in local.mk)"; exit 1; }
	rm -rf dist && (cd $(PMAI) && uv build -o $(CURDIR)/dist) && rm dist/*.tar.gz
	$(if $(SKILLS_REF),$(GIT) -C $(SKILLS) archive $(SKILLS_REF) skills | tar -x -C dist,rsync -a --exclude __pycache__ $(SKILLS)/skills dist/)
	echo "pmai: $(PMAI) $(call rev,$(PMAI))"
	echo "skills: $(SKILLS) $(or $(SKILLS_REF),working tree) $(call rev,$(SKILLS),$(SKILLS_REF))"
	docker build -t pmai-eval:latest --build-arg SANDBOX=$(SANDBOX) -f docker/eval/Dockerfile .

viewer:  ## pmai-viewer:latest = headless Chromium + docker/viewer/server.py + the PMView build of PMVIEW
	rm -rf dist/pmview && mkdir -p dist/pmview
	$(if $(PMVIEW),rsync -a $(PMVIEW)/build/ dist/pmview/ && echo "$(call rev,$(PMVIEW))" > dist/pmview/VERSION && echo "pmview: $(PMVIEW) $$(cat dist/pmview/VERSION)")
	docker build -t pmai-viewer:latest -f docker/viewer/Dockerfile .

run:  ## make run JOB=evals/<eval>/<job>.yaml [CASE=<case>]
	@test -f .env || { echo "No .env: copy .env.example to .env and add the keys."; exit 1; }
	set -a && . ./.env && set +a && HARBOR_TELEMETRY=off uv run harbor run -c $(JOB) --job-name $(NAME) --jobs-dir results \
	  $(if $(CASE),-p $(dir $(JOB))cases/$(CASE))

watch:  ## follow the newest job as it runs (in a second shell); make watch JOB=results/<job> for another
	uv run python scripts/watch.py $(if $(filter results/%,$(JOB)),$(JOB))

# Harbor's viewer on $(PORT) only (the tunnel): after a restart, wait for the old connections to close (up to 60 s)
view:  ## all runs: one job for each job file, one row and one Pareto point for each run; restart to see new trials
	uv run python -m pmai_evals.review combine results results/.view
	@for i in $$(seq 30); do python3 -c "import socket; socket.socket().bind(('127.0.0.1', $(PORT)))" 2>/dev/null && break; \
	  echo "port $(PORT) is busy, waiting"; sleep 2; done
	HARBOR_TELEMETRY=off uv run harbor view results/.view --port $(PORT)

review:  ## the review page on this machine, all runs of results/: each click saves to evals/<eval>/ratings/<run>.json
	uv run python -m pmai_evals.review serve results $(PORT)

test:  ## unit tests (no Docker)
	uv run pytest -q

lint:  ## ruff
	uv run ruff check src tests evals scripts docker
