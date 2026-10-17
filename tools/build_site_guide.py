# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Builds the user guide of the website (website/pages/) from docs/index.html: the sections a user needs, the screenshots copied
# Houdini : 21 and 22 (plain Python, no Houdini needed)
# Version : 1.0.0
#
# usage: python tools/build_site_guide.py
# The documentation of the repository stays the single source: run this again after a change of docs/index.html.

import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs", "index.html")
OUT = os.path.join(ROOT, "website")
KEEP = ("overview", "install", "quickstart", "network", "ui", "presets", "compat", "security", "troubleshooting", "license")
GITHUB = "https://github.com/bsm3d/Karma-builder"


# ------------------------------------------------------------
def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ------------------------------------------------------------
def sections(main):
    parts = re.split(r'(?=<h2 id=")', main)
    found = {}
    for part in parts:
        match = re.match(r'<h2 id="([^"]+)"', part)
        if match:
            found[match.group(1)] = part.rstrip() + "\n"
    return found


# ------------------------------------------------------------
def toc(nav, keep):
    groups = []
    for line in nav.splitlines():
        if re.match(r'^    <li><a href="#', line):
            groups.append([line])
        elif groups and line.strip() not in ("</ol>", "<ol>"):
            groups[-1].append(line)
    items = ["\n".join(group) for group in groups if re.match(r'\s*<li><a href="#([^"]+)"', group[0]).group(1) in keep]
    return "<ol>\n" + "\n".join(items) + "\n</ol>\n"


# ------------------------------------------------------------
def main():
    text = read(DOCS)
    nav = re.search(r"<nav[^>]*>(.*?)</nav>", text, re.S).group(1)
    body = re.search(r"<main>(.*?)</main>", text, re.S).group(1)
    first = body.index('<h2 id="')
    found = sections(body[first:])
    missing = [name for name in KEEP if name not in found]
    if missing:
        raise SystemExit("sections not found in docs/index.html: {}".format(missing))
    content = "".join(found[name] for name in KEEP)
    content = content.replace('src="screenshots/', 'src="{{assets}}/img/shots/')
    content = content.replace('href="../LICENSE"', 'href="{}/blob/main/LICENSE"'.format(GITHUB))
    content = re.sub(r'<code>README\.md</code>', '<code>README.md</code>', content)
    if " style=" in content:
        raise SystemExit("an inline style in the guide: the site forbids them (Content-Security-Policy)")
    pages = os.path.join(OUT, "pages")
    os.makedirs(pages, exist_ok=True)
    with open(os.path.join(pages, "guide_content.inc.html"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    with open(os.path.join(pages, "guide_toc.inc.html"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(toc(nav, KEEP))
    shots = os.path.join(OUT, "assets", "img", "shots")
    os.makedirs(shots, exist_ok=True)
    for name in os.listdir(os.path.join(ROOT, "docs", "screenshots")):
        if name.endswith(".png"):
            shutil.copyfile(os.path.join(ROOT, "docs", "screenshots", name), os.path.join(shots, name))
    print("guide: {} sections, {} characters, {} screenshots".format(len(KEEP), len(content), len(os.listdir(shots))))


if __name__ == "__main__":
    main()
