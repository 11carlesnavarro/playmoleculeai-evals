"""Pure read-only JS observers exposed to Python.

These are the *only* JS snippets the harness runs in the page. They never
mutate state, never intercept network calls, and never write files. They
are passed to ``page.evaluate(...)`` from :class:`ChatSession`.

Snippets are pulled from the old ``pmvier_browser.py`` (recoverable via
``git show d6df665:scripts/pmvier_browser.py``) and reduced to their
minimal observer form.
"""

from __future__ import annotations

# Returns a base64 data URI for the current Molstar viewport.
SCREENSHOT_DATA_URI = """
() => {
    const viewer = window.molstar?.helpers?.viewportScreenshot;
    if (!viewer) return null;
    try {
        return viewer.getImageDataUri();
    } catch (err) {
        return null;
    }
}
"""

# Returns the JSON-encoded systems_tree from the in-page Pyodide worker.
# Falls back to null if Pyodide isn't ready yet.
VIEWER_STATE_JSON = """
async () => {
    if (!window.pyodideWorker) return null;
    try {
        const result = await window.pyodideWorker.RunPythonAsync({
            context: {},
            script: 'import json, _internal_py_utils\\njson.dumps(_internal_py_utils.systems_tree)'
        });
        return result;
    } catch (err) {
        return JSON.stringify({_error: String(err)});
    }
}
"""

# Pyodide-readiness probe.
PYODIDE_READY = "() => Boolean(window.pyodideWorker && window.molstar)"
