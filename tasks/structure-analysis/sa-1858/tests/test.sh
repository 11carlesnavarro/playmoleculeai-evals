#!/bin/bash
PYTHONPATH=/opt exec /opt/grader/bin/pytest /tests -q -p pmai_evals.reward
