# pmai-viewer: headless Chromium that opens the deployed PMView site, driven by server.py.
# dist/pmview/: a PMView build (make viewer PMVIEW=<checkout>) that replaces the site's PMView; empty: the site's.
# Chromium and its libraries are in the image; the Python package is not.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
RUN python3 -m pip install --no-cache-dir "playwright==1.58.0" "aiohttp>=3.10"
COPY dist/pmview/ /srv/pmview/
COPY docker/viewer/server.py /srv/viewer/
EXPOSE 9000
CMD ["python3", "/srv/viewer/server.py"]
