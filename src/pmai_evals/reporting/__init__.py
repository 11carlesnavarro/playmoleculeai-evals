"""Reporting layer: aggregate graded runs into reports."""

from pmai_evals.reporting.aggregate import aggregate_run
from pmai_evals.reporting.render import render_html, render_json, render_markdown

__all__ = ["aggregate_run", "render_html", "render_json", "render_markdown"]
