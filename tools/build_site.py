# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Builds the static pages of the website (website/) from website/src and docs/index.html: header and footer are put in every page, no script does it at the visit
# Houdini : 21 and 22 (plain Python, no Houdini needed)
# Version : 1.0.0
#
# usage: python tools/build_site.py
# Reads    website/src/site.json (address of the site), layout.html, pages/*.html, faq.json and the documentation of the tool
# Writes   website/index.html, guide/, faq/, contact/ (each an index.html), 404.html, sitemap.xml, robots.txt, and the screenshots of the guide
# Run it again after a change of one of these sources or of docs/index.html, then upload the website folder.

import hashlib
import json
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "website")
SRC = os.path.join(SITE, "src")
DOCS = os.path.join(ROOT, "docs", "index.html")
GUIDE_KEEP = ("overview", "install", "quickstart", "network", "ui", "presets", "compat", "security", "troubleshooting", "license")
NAV = (("home", "Home", "/"), ("guide", "User guide", "/guide/"), ("faq", "FAQ", "/faq/"), ("contact", "Contact", "/contact/"))
URLS = {"home": "/", "guide": "/guide/", "faq": "/faq/", "contact": "/contact/"}


# ------------------------------------------------------------
def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ------------------------------------------------------------
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


# ------------------------------------------------------------
def tool_version():
    found = re.search(r'^SCRIPT_VERSION = "([^"]+)"', read(os.path.join(ROOT, "bsm_karma", "config.py")), re.M)
    if not found:
        raise SystemExit("SCRIPT_VERSION not found in bsm_karma/config.py")
    return found.group(1)


# ------------------------------------------------------------
# The address of an asset carries a short hash of the file, so that a changed file is fetched again by the browsers.
def asset_url(path):
    full = os.path.join(SITE, "assets", path)
    if not os.path.isfile(full):
        raise SystemExit("asset not found: " + path)
    with open(full, "rb") as handle:
        digest = hashlib.md5(handle.read()).hexdigest()[:8]
    return "/assets/{}?v={}".format(path, digest)


# ------------------------------------------------------------
def fill(text, values):
    text = re.sub(r"\{\{asset:([^}]+)\}\}", lambda m: asset_url(m.group(1)), text)
    text = re.sub(r"\{\{url:([a-z]+)\}\}", lambda m: URLS[m.group(1)], text)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    left = re.findall(r"\{\{[^}]*\}\}", text)
    if left:
        raise SystemExit("placeholders left: {}".format(left[:3]))
    return text


# ------------------------------------------------------------
def ld_block(data):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return '<script type="application/ld+json">{}</script>\n'.format(raw)


# ------------------------------------------------------------
def guide_parts():
    text = read(DOCS)
    nav = re.search(r"<nav[^>]*>(.*?)</nav>", text, re.S).group(1)
    main = re.search(r"<main>(.*?)</main>", text, re.S).group(1)
    sections = {}
    for part in re.split(r'(?=<h2 id=")', main[main.index('<h2 id="'):]):
        found = re.match(r'<h2 id="([^"]+)"', part)
        if found:
            sections[found.group(1)] = part.rstrip() + "\n"
    missing = [name for name in GUIDE_KEEP if name not in sections]
    if missing:
        raise SystemExit("sections not found in docs/index.html: {}".format(missing))
    content = "".join(sections[name] for name in GUIDE_KEEP)
    content = content.replace('src="screenshots/', 'src="{{asset:img/shots/')
    content = re.sub(r'(\{\{asset:img/shots/[a-z0-9_]+\.png)"', r'\1}}"', content)
    content = content.replace('href="../LICENSE"', 'href="{{github_url}}/blob/main/LICENSE"')
    if " style=" in content:
        raise SystemExit("an inline style in the guide: the site forbids them (Content-Security-Policy)")
    groups = []
    for line in nav.splitlines():
        if re.match(r'^    <li><a href="#', line):
            groups.append([line])
        elif groups and line.strip() not in ("</ol>", "<ol>"):
            groups[-1].append(line)
    items = ["\n".join(group) for group in groups if re.match(r'\s*<li><a href="#([^"]+)"', group[0]).group(1) in GUIDE_KEEP]
    toc = "<ol>\n" + "\n".join(items) + "\n</ol>"
    shots = os.path.join(SITE, "assets", "img", "shots")
    os.makedirs(shots, exist_ok=True)
    for name in os.listdir(os.path.join(ROOT, "docs", "screenshots")):
        if name.endswith(".png"):
            shutil.copyfile(os.path.join(ROOT, "docs", "screenshots", name), os.path.join(shots, name))
    return toc, content


# ------------------------------------------------------------
def faq_parts(config):
    data = json.loads(read(os.path.join(SRC, "faq.json")))
    html = []
    entities = []
    for group in data["groups"]:
        html.append("  <h2>{}</h2>".format(group["title"]))
        for item in group["items"]:
            html.append('  <details class="qa" id="{id}">\n    <summary>{q}</summary>\n    <p>{a}</p>\n  </details>'.format(**item))
            plain = re.sub(r"<[^>]+>", "", item["a"])
            plain = plain.replace("&rarr;", "->").replace("&amp;", "&")
            plain = re.sub(r"\{\{url:[a-z]+\}\}", "", plain)
            entities.append({"@type": "Question", "name": item["q"], "acceptedAnswer": {"@type": "Answer", "text": plain.strip()}})
    body = ('<div class="wrap narrow">\n  <h1>FAQ</h1>\n  <p class="lead">Short answers. The <a href="{{url:guide}}">user guide</a> has the full detail, '
            'and the <a href="{{url:contact}}">contact page</a> is the way to reach me.</p>\n' + "\n".join(html) +
            '\n  <p class="callout">Still stuck? <a href="{{url:contact}}">Send me a message</a>.</p>\n</div>\n')
    return body, {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}


# ------------------------------------------------------------
def main():
    config = json.loads(read(os.path.join(SRC, "site.json")))
    version = tool_version()
    site_url = config["site_url"].rstrip("/")
    layout = read(os.path.join(SRC, "layout.html"))
    toc, guide_content = guide_parts()
    faq_body, faq_ld = faq_parts(config)
    base = {"name": config["name"], "site_url": site_url, "github_url": config["github_url"], "version": version}
    pages = {
        "home": {
            "title": "{} | Karma render setup for Houdini".format(config["name"]),
            "description": "Karma Builder builds and updates a complete Karma render setup in Houdini Solaris: camera, sky, lights, materials, render settings. For Houdini 21 and 22.",
            "body": read(os.path.join(SRC, "pages", "home.html")),
            "ld": {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": config["name"], "applicationCategory": "DeveloperApplication",
                   "operatingSystem": "Windows, Linux, macOS (inside SideFX Houdini 21 and 22)", "softwareVersion": version,
                   "author": {"@type": "Person", "name": "Benoît Saint-Moulin", "url": "https://www.bsm3d.com"},
                   "description": "A tool for SideFX Houdini that builds and updates a Karma render setup in Solaris."},
            "out": "index.html", "path": "/"},
        "guide": {
            "title": "User guide | {}".format(config["name"]),
            "description": "How to install and use Karma Builder in Houdini: quick start, what gets built, every tab of the window, presets, troubleshooting.",
            "body": ('<div class="wrap guide">\n  <nav class="toc" aria-label="Table of contents">' + toc + '</nav>\n  <article class="doc">\n    <h1>User guide</h1>\n'
                     '    <p class="lead">Version ' + version + ', for Houdini 21 and 22. Something not here? Try the <a href="{{url:faq}}">FAQ</a> or '
                     '<a href="{{url:contact}}">write to me</a>.</p>\n' + guide_content + '  </article>\n</div>\n'),
            "ld": None, "out": os.path.join("guide", "index.html"), "path": "/guide/"},
        "faq": {
            "title": "FAQ | {}".format(config["name"]),
            "description": "Answers about Karma Builder: Houdini versions, license for students, freelancers and studios, installation problems, privacy.",
            "body": faq_body, "ld": faq_ld, "out": os.path.join("faq", "index.html"), "path": "/faq/"},
        "contact": {
            "title": "Contact | {}".format(config["name"]),
            "description": "Write to the author of Karma Builder: a question, a bug report, or a commercial license for your studio.",
            "body": read(os.path.join(SRC, "pages", "contact.html")), "ld": None, "out": os.path.join("contact", "index.html"), "path": "/contact/"},
        "404": {
            "title": "Page not found | {}".format(config["name"]), "description": "This page does not exist.",
            "body": read(os.path.join(SRC, "pages", "404.html")), "ld": None, "out": "404.html", "path": "/404.html", "noindex": True},
    }
    for key, page in pages.items():
        nav = "".join('      <a href="{}"{}>{}</a>\n'.format(url, ' aria-current="page"' if key == name else "", label) for name, label, url in NAV)
        head_extra = ld_block(page["ld"]) if page["ld"] else ""
        content = fill(page["body"], base)
        html = fill(layout, dict(base, title=page["title"], description=page["description"], canonical=site_url + page["path"], page=key, nav=nav,
                                 robots=("noindex, " if page.get("noindex") else "") + "noai, noimageai",
                                 content=content, head_extra=head_extra))
        write(os.path.join(SITE, page["out"]), html)
    urls = "".join("  <url><loc>{}</loc><changefreq>{}</changefreq></url>\n".format(site_url + path, freq)
                   for path, freq in (("/", "weekly"), ("/guide/", "weekly"), ("/faq/", "monthly"), ("/contact/", "yearly")))
    write(os.path.join(SITE, "sitemap.xml"), '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
    # AI robots and assistants, the ones that fetch a page for a person included (the .htaccess shuts the same names out for the ones that ignore this file)
    ai_robots = ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web", "Claude-User", "Claude-SearchBot", "anthropic-ai", "CCBot", "Bytespider",
                 "Amazonbot", "meta-externalagent", "meta-externalfetcher", "FacebookBot", "cohere-ai", "Diffbot", "ImagesiftBot", "Omgilibot", "PetalBot", "Timpibot",
                 "PerplexityBot", "Perplexity-User", "MistralAI-User", "DuckAssistBot", "YouBot", "Google-CloudVertexBot", "GoogleAgent-Mariner", "Google-Extended", "Applebot-Extended")
    robots = "".join("User-agent: {}\n".format(name) for name in ai_robots) + "Disallow: /\n\n"
    robots += "User-agent: *\nDisallow: /admin.php\nDisallow: /hit.php\nDisallow: /go.php\nDisallow: /contact.php\nDisallow: /token.php\nDisallow: /data/\nAllow: /\n\n"
    write(os.path.join(SITE, "robots.txt"), robots + "Sitemap: {}/sitemap.xml\n".format(site_url))
    print("built {} pages for {} (tool version {}), guide of {} sections".format(len(pages), site_url, version, len(GUIDE_KEEP)))


if __name__ == "__main__":
    main()
