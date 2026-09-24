MAZZI LAB - FIXED EXTRACTOR

This is the flat Render Web Service build.

Files are all at the root:
app.py
index.html
style.css
requirements.txt
Dockerfile
render.yaml

The Docker image now installs multiple archive engines:
- 7-Zip / 7zz
- libarchive / bsdtar
- unzip
- unrar

The server tries them in order, so an archive that fails with one extractor
can be handled by another.

Deploy as a Render WEB SERVICE, not a Static Site.

The upload endpoint also handles non-JSON/empty responses safely and truncates
large extractor errors so the browser does not get flooded with messages.
