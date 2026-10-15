# pmai-eval: the production sandbox image, plus pmai and a grader (each in its own venv) and the skills.
ARG SANDBOX
FROM ${SANDBOX}
USER root
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv

# the grader: its own venv, so the tests do not depend on the sandbox's python
# (first: a new pmai wheel does not install it again). The versions are those of uv.lock.
RUN uv venv /opt/grader --python 3.12 \
 && uv pip install --python /opt/grader pytest==9.1.1 openai==2.54.0

# the agent: only the pmai command is on PATH, so tools still see the sandbox python
COPY dist/*.whl /tmp/dist/
RUN uv venv /opt/pmai --python 3.12 \
 && uv pip install --python /opt/pmai /tmp/dist/playmoleculeai-*.whl \
 && ln -s /opt/pmai/bin/pmai /usr/local/bin/pmai && rm -rf /tmp/dist

# the skills, as the production agent image has them: acellera-skills/skills at /home/.pmai/skills
# (the sandbox image has none)
COPY dist/skills/ /home/.pmai/skills/
ENV PMAI_HOME=/home/.pmai
COPY docker/agent_config.yaml /opt/pmai-config/
COPY src/pmai_evals/ /opt/pmai_evals/
WORKDIR /app
# [verify] `docker run --rm $SANDBOX id`: restore the sandbox's own USER here if it is not root
