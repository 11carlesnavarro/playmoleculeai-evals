# pmai-eval: the production sandbox image, plus pmai and a grader (each in its own venv) and the skills.
ARG SANDBOX
FROM ${SANDBOX}
USER root
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# the grader: pinned, so reference values do not move when the sandbox moves
# (first: a new pmai wheel does not install it again)
RUN uv venv /opt/grader --python 3.12 \
 && uv pip install --python /opt/grader pytest anthropic pandas rdkit "moleculekit<1.12"

# the agent: only the pmai command is on PATH, so tools still see the sandbox python
COPY dist/*.whl /tmp/dist/
RUN uv venv /opt/pmai --python 3.12 \
 && uv pip install --python /opt/pmai /tmp/dist/playmoleculeai-*.whl \
 && ln -s /opt/pmai/bin/pmai /usr/local/bin/pmai && rm -rf /tmp/dist

# the skills, as the production agent image has them: acellera-skills/skills at /home/.pmai/skills
# (the sandbox image has none: no SKILL.md reached the agent in the phase 2 trials)
COPY dist/skills/ /home/.pmai/skills/
ENV PMAI_HOME=/home/.pmai
COPY config/ /opt/pmai-config/
COPY src/pmai_evals/ /opt/pmai_evals/
WORKDIR /app
# [verify] `docker run --rm $SANDBOX id`: restore the sandbox's own USER here if it is not root
