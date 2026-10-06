SANDBOX ?= europe-southwest1-docker.pkg.dev/repositories-368911/acellera-docker-apps/pm-python-sandbox:latest
PMAI ?= ../playmoleculeAI
JOB ?= experiments/smoke.yaml
# a new jobs/ folder per run; NAME=<an old job> resumes that job (Harbor keeps its finished trials)
NAME ?= $(basename $(notdir $(JOB)))-$(shell date +%Y%m%d-%H%M%S)

.PHONY: image run view test lint

# sdist first, then the wheel from it: a direct wheel build reuses $(PMAI)/build/lib,
# which keeps files deleted from src
image:  ## pmai-eval:latest = sandbox image + pmai + grader
	rm -rf dist && (cd $(PMAI) && uv build -o $(CURDIR)/dist) && rm dist/*.tar.gz
	docker build -t pmai-eval:latest --build-arg SANDBOX=$(SANDBOX) -f image/Dockerfile .

run:  ## make run JOB=experiments/smoke.yaml
	set -a && . ./.env && set +a && HARBOR_TELEMETRY=off uv run harbor run -c $(JOB) --job-name $(NAME)

view:
	HARBOR_TELEMETRY=off uv run harbor view jobs

test:
	uv run pytest -q

lint:
	uv run ruff check src tests tasks scripts
