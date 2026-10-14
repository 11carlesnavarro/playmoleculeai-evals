SANDBOX ?= europe-southwest1-docker.pkg.dev/repositories-368911/acellera-docker-apps/pm-python-sandbox:latest
# viewer-quality hill climb (2026-10-09): the images come from the three worktrees, branch viewer-quality.
# Production: PMAI=../playmoleculeAI SKILLS=../../acellera/acellera-skills SKILLS_REF=main PMVIEW=
PMAI ?= ../playmoleculeAI-2-viewer-quality
SKILLS ?= ../../acellera/acellera-skills-viewer-quality
# PMView in pmai-viewer: the build/ of a checkout (npm run build there first), or empty = the deployed site's
PMVIEW ?= ../pmview-viewer-quality
# skills baked in the image: a git ref (production: main), or empty = the working tree with its changes
SKILLS_REF ?=
# the repos belong to carles, and make image runs as slurmweb: git refuses them without this
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

.PHONY: image viewer run watch view review test lint

# sdist first, then the wheel from it: a direct wheel build reuses $(PMAI)/build/lib,
# which keeps files deleted from src
image:  ## pmai-eval:latest = sandbox image + pmai + grader + skills
	rm -rf dist && (cd $(PMAI) && uv build -o $(CURDIR)/dist) && rm dist/*.tar.gz
	$(if $(SKILLS_REF),$(GIT) -C $(SKILLS) archive $(SKILLS_REF) skills | tar -x -C dist,rsync -a --exclude __pycache__ $(SKILLS)/skills dist/)
	echo "pmai: $(PMAI) $(call rev,$(PMAI))"
	echo "skills: $(SKILLS) $(or $(SKILLS_REF),working tree) $(call rev,$(SKILLS),$(SKILLS_REF))"
	docker build -t pmai-eval:latest --build-arg SANDBOX=$(SANDBOX) -f docker/eval/Dockerfile .

viewer:  ## pmai-viewer:latest = headless Chromium + docker/viewer/server.py + the PMView build of $(PMVIEW)
	rm -rf dist/pmview && mkdir -p dist/pmview
	$(if $(PMVIEW),rsync -a $(PMVIEW)/build/ dist/pmview/ && echo "$(call rev,$(PMVIEW))" > dist/pmview/VERSION && echo "pmview: $(PMVIEW) $$(cat dist/pmview/VERSION)")
	docker build -t pmai-viewer:latest -f docker/viewer/Dockerfile .

run:  ## make run JOB=evals/<eval>/<job>.yaml [CASE=<case>]
	set -a && . ./.env && set +a && HARBOR_TELEMETRY=off uv run harbor run -c $(JOB) --job-name $(NAME) --jobs-dir results \
	  $(if $(CASE),-p $(dir $(JOB))cases/$(CASE))

watch:  ## follow the newest job as it runs (in a second shell); make watch JOB=results/<job> for another
	uv run python scripts/watch.py $(if $(filter results/%,$(JOB)),$(JOB))

view:  ## one job for each job file, all its runs in it (one row and one Pareto point each), restart to see new trials;
       ## $(PORT) only (the tunnel): after a restart, wait for the old connections to close (up to 60 s)
	uv run python -m pmai_evals.review combine results results/.view
	@for i in $$(seq 30); do python3 -c "import socket; socket.socket().bind(('127.0.0.1', $(PORT)))" 2>/dev/null && break; \
	  echo "port $(PORT) is busy, waiting"; sleep 2; done
	HARBOR_TELEMETRY=off uv run harbor view results/.view --port $(PORT)

review:  ## the review page on this machine, all runs of results/: each click saves to evals/<eval>/ratings/<run>.json
	uv run python -m pmai_evals.review serve results $(PORT)

test:
	uv run pytest -q

lint:
	uv run ruff check src tests evals scripts docker
