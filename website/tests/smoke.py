# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Functional tests of the website: a copy runs on the PHP built-in server and each check is a real request.

# Functional tests, each one a real request to a copy on the PHP built-in server (PHP 8.1 or later on the path).
# The built-in server ignores .htaccess, so headers and deny rules are not tested here.
# usage: python website/tests/smoke.py

import html.parser
import glob
import http.client
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
# against a real Apache instead: BSM_PORT=8890 BSM_DIR=/path/of/the/copy BSM_USER=www-data python website/tests/smoke.py (the database is then read as that user)
PORT = int(os.environ.get("BSM_PORT", "8765"))
KEY = "smoke-test-key"
OUTSIDE = os.environ.get("BSM_DIR", "")
OUTSIDE_USER = os.environ.get("BSM_USER", "")
results = []

# ------------------------------------------------------------
def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)[:200]) if detail != "" else ""))

# ------------------------------------------------------------
def prepare():
    work = tempfile.mkdtemp(prefix="bsm_site_")
    target = os.path.join(work, "site")
    shutil.copytree(SITE, target, ignore=shutil.ignore_patterns("config.php", "*.sqlite*", "__pycache__"))
    password_hash = subprocess.run(["php", "-r", "echo password_hash('%s', PASSWORD_DEFAULT);" % KEY], capture_output=True, text=True).stdout
    config = open(os.path.join(target, "inc", "config.sample.php"), encoding="utf-8").read()
    config = config.replace("'admin_hash'  => ''", "'admin_hash'  => '%s'" % password_hash).replace("'salt'        => ''", "'salt'        => 'test-salt-of-at-least-sixteen-characters'")
    config = config.replace("you@example.com", "owner@example.com")
    with open(os.path.join(target, "inc", "config.php"), "w", encoding="utf-8") as handle:
        handle.write(config)
    return work, target

# ------------------------------------------------------------
class Client:
    def __init__(self):
        self.cookies = {}

    def request(self, method, path, data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        headers = dict(headers or {})
        headers.setdefault("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) Firefox/120.0")
        if self.cookies:
            headers["Cookie"] = "; ".join("%s=%s" % item for item in self.cookies.items())
        body = raw
        if data is not None:
            body = urllib.parse.urlencode(data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8", "replace")
        for header, value in response.getheaders():
            if header.lower() == "set-cookie":
                name, _, rest = value.partition("=")
                self.cookies[name] = rest.split(";")[0]
        connection.close()
        return response.status, dict((k.lower(), v) for k, v in response.getheaders()), text

# ------------------------------------------------------------
def database(target):
    found = glob.glob(os.path.join(target, "data", "site-*.sqlite"))
    return found[0] if found else os.path.join(target, "data", "missing.sqlite")

# ------------------------------------------------------------
def as_user(target, sql, args):
    script = "import sqlite3, sys, json\nc = sqlite3.connect(sys.argv[1])\nr = c.execute(sys.argv[2], json.loads(sys.argv[3])).fetchall()\nc.commit()\nprint(json.dumps(r))"
    out = subprocess.run(["runuser", "-u", OUTSIDE_USER, "--", sys.executable, "-c", script, database(target), sql, json.dumps(list(args))], capture_output=True, text=True, check=True).stdout
    return [tuple(row) for row in json.loads(out)]

# ------------------------------------------------------------
def query(target, sql, args=()):
    if OUTSIDE_USER:
        return as_user(target, sql, args)
    connection = sqlite3.connect(database(target))
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()

# ------------------------------------------------------------
def execute(target, sql, args=()):
    if OUTSIDE_USER:
        as_user(target, sql, args)
        return
    connection = sqlite3.connect(database(target))
    connection.execute(sql, args)
    connection.commit()
    connection.close()

# ------------------------------------------------------------
def token_of(html):
    found = re.search(r'name="csrf" value="([0-9a-f]+)"', html)
    return found.group(1) if found else ""

# ------------------------------------------------------------
VOID = {"meta", "link", "img", "input", "br", "hr", "source", "area", "base", "col", "wbr", "embed", "param", "track"}

class Audit(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.ids, self.hrefs, self.srcs, self.anchors = [], [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.hrefs.append(attrs["href"])
            if attrs.get("target") == "_blank" and "noopener" not in attrs.get("rel", ""):
                self.errors.append("target=_blank without rel=noopener: " + attrs["href"])
        if tag in ("img", "script", "link") and (attrs.get("src") or attrs.get("href")):
            self.srcs.append(attrs.get("src") or attrs.get("href"))
        if tag == "img" and "alt" not in attrs:
            self.errors.append("img without alt: " + str(attrs.get("src")))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append("unbalanced </%s> (open: %s)" % (tag, self.stack[-3:]))
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()

# ------------------------------------------------------------
def audit_pages(client):
    pages = (("/", "home"), ("/guide/", "guide"), ("/faq/", "faq"), ("/contact/", "contact"), ("/404.html", "404"))
    for path, name in pages:
        text = client.request("GET", path)[2]
        parser = Audit()
        parser.feed(text)
        problems = list(parser.errors)
        if parser.stack:
            problems.append("tags left open: %s" % parser.stack)
        dupes = {i for i in parser.ids if parser.ids.count(i) > 1}
        if dupes:
            problems.append("duplicate ids: %s" % sorted(dupes))
        for href in parser.hrefs:
            if href.startswith("#") and href[1:] not in parser.ids:
                problems.append("anchor without target: " + href)
            elif href.startswith("/") and not href.startswith("//"):
                target_path = href.split("#")[0].split("?")[0]
                if target_path == "/go.php":
                    continue
                local = os.path.join(SITE, target_path.lstrip("/"))
                if target_path.endswith("/"):
                    local = os.path.join(local, "index.html")
                if not os.path.isfile(local):
                    problems.append("broken local link: " + href)
                elif "#" in href and local.endswith(".html"):
                    fragment = href.split("#")[1]
                    if 'id="%s"' % fragment not in open(local, encoding="utf-8").read():
                        problems.append("link to a missing section: " + href)
        for src in parser.srcs:
            if src.startswith("/") and not os.path.isfile(os.path.join(SITE, src.split("?")[0].lstrip("/"))):
                problems.append("missing file: " + src)
        if "{{" in text:
            problems.append("a placeholder is left")
        check("HTML of %s: balanced, unique ids, links and files resolve, images have alt" % name, not problems, problems[:4])

# ------------------------------------------------------------
def main():
    work, target = prepare()
    server = subprocess.Popen(["php", "-S", "127.0.0.1:%d" % PORT, "-t", target, os.path.join(target, "tests", "router.php")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if not OUTSIDE else None
    if OUTSIDE:
        target = OUTSIDE
    try:
        for _ in range(50):
            try:
                Client().request("GET", "/")
                break
            except OSError:
                time.sleep(0.1)
        run(target)
    finally:
        if server:
            server.terminate()
            server.wait(5)
        shutil.rmtree(work, ignore_errors=True)
    print("\nRESULT:", "all %d checks passed" % len(results) if all(results) else "%d FAILED of %d" % (results.count(False), len(results)))
    sys.exit(0 if all(results) else 1)

# ------------------------------------------------------------
def run(target):
    # --- the static pages
    visitor = Client()
    for path, word in (("/", "A Karma render setup in one window"), ("/guide/", "Quick start"), ("/faq/", "Is it free?"), ("/contact/", "Your message"), ("/404.html", "Page not found")):
        status, headers, html = visitor.request("GET", path)
        check("page %s is served and has its content" % path, status == 200 and word in html, status)
    check("an unknown page is a 404", visitor.request("GET", "/nothing-here/")[0] == 404)
    check("no cookie on any public page", not visitor.cookies, visitor.cookies)
    home = visitor.request("GET", "/")[2]
    check("the menu is in the HTML itself, no script puts it there", 'aria-current="page">Home' in home and '<a href="/guide/">User guide</a>' in home and "<footer" in home)
    check("the canonical address and the page counter name are set", '<link rel="canonical" href="' in home and 'data-page="home"' in home)
    check("no inline style or script that the CSP would block", not re.search(r'<[^>]+ style="', home) and not re.search(r"<script(?![^>]*(src=|application/ld\+json))", home))
    guide_html = visitor.request("GET", "/guide/")[2]
    check("the guide has its screenshots and its table of contents", "/assets/img/shots/scene.png" in guide_html and 'class="toc"' in guide_html and "Install.bat" in guide_html)
    faq_html = visitor.request("GET", "/faq/")[2]
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', faq_html, re.S)
    try:
        data = json.loads(blocks[0])
        check("the FAQ structured data is valid JSON with every question", data["@type"] == "FAQPage" and len(data["mainEntity"]) == faq_html.count('<details class="qa"'), len(data["mainEntity"]))
    except (IndexError, ValueError) as exc:
        check("the FAQ structured data is valid JSON", False, exc)
    check("the sitemap lists the four pages", visitor.request("GET", "/sitemap.xml")[2].count("<loc>") == 4)
    check("robots.txt keeps the private addresses out and names the sitemap", "Disallow: /admin.php" in visitor.request("GET", "/robots.txt")[2] and "Sitemap:" in visitor.request("GET", "/robots.txt")[2])
    htaccess = open(os.path.join(SITE, ".htaccess"), encoding="utf-8").read()
    check("the .htaccess sends the security headers of the static pages", all(word in htaccess for word in ("X-Frame-Options", "frame-ancestors 'none'", "nosniff", "ErrorDocument 404")))
    audit_pages(visitor)

    # --- the contact form: a token from the server, a post that answers in JSON
    execute_limits = lambda: execute(target, "DELETE FROM limits")
    messages = lambda: query(target, "SELECT COUNT(*) FROM messages")[0][0]
    good = {"name": "Ada", "email": "ada@example.org", "topic": "bug", "message": "The sky stays black in my scene, Houdini 22.0.466."}

    def token(client=None, wait=True):
        status, headers, text = (client or Client()).request("GET", "/token.php")
        value = json.loads(text)["token"]
        if wait:
            time.sleep(3.2)
        return value

    def post(fields, client=None, headers=None):
        status, response_headers, text = (client or Client()).request("POST", "/contact.php", fields, headers=headers)
        try:
            return status, json.loads(text)
        except ValueError:
            return status, {"raw": text}

    status, headers, text = Client().request("GET", "/token.php")
    value = json.loads(text)["token"]
    check("the token endpoint gives a signed token and sets no cookie", status == 200 and re.fullmatch(r"\d+\.[0-9a-f]{16}\.[0-9a-f]{32}", value) and "set-cookie" not in headers and "no-store" in headers.get("cache-control", ""), value)
    check("token.php only takes GET, contact.php only takes POST", Client().request("POST", "/token.php", {})[0] == 405 and Client().request("GET", "/contact.php")[0] == 405)
    status, data = post(dict(good, token=""))
    check("a post without a token is refused and nothing is stored", status == 400 and not data["ok"] and messages() == 0, (status, data))
    status, data = post(dict(good, token=value))
    check("a token younger than three seconds is a robot: told it worked, nothing kept", status == 200 and data["ok"] and messages() == 0, (status, data))
    time.sleep(3.2)
    forged = value[:-1] + ("0" if value[-1] != "0" else "1")
    status, data = post(dict(good, token=forged))
    check("a token with a changed signature is refused", status == 400 and messages() == 0)
    older = str(int(value.split(".")[0]) - 3 * 3600) + "." + ".".join(value.split(".")[1:])
    status, data = post(dict(good, token=older))
    check("a token with a changed date is refused", status == 400 and messages() == 0)
    status, data = post(dict(good, token=value))
    check("a good message with a token of the server is accepted", status == 200 and data["ok"] and messages() == 1, (status, data))
    rows = query(target, "SELECT name, email, topic, message FROM messages")
    check("it is in the database with its fields", rows == [("Ada", "ada@example.org", "bug", good["message"])], rows)
    execute(target, "DELETE FROM limits WHERE bucket LIKE 'contact:%'")
    status, data = post(dict(good, token=value))
    check("a token is used up when its message is stored", status == 400 and messages() == 1, (status, data))
    status, data = post(dict(good, token=token(), _gotcha="http://spam.example"))
    check("the honeypot: success is shown, nothing is kept", status == 200 and data["ok"] and messages() == 1)
    execute_limits()
    wait_token = token()
    status, data = post(dict(good, token=wait_token, email="a@b.com\r\nBcc: victim@example.org"))
    check("a header injected through the email is refused", status == 422 and any("email" in e for e in data["errors"]) and messages() == 1, (status, data))
    status, data = post(dict(good, token=wait_token, name="Eve\r\nBcc: victim@example.org"))
    name = query(target, "SELECT name FROM messages ORDER BY id DESC LIMIT 1")[0][0]
    check("after a refusal the same token still works, and line breaks of the name are taken out", status == 200 and name.startswith("Eve") and "\n" not in name and "\r" not in name, (status, name))
    execute_limits()
    for label, change in (("an empty name", {"name": ""}), ("a short message", {"message": "hi"}), ("an unknown topic", {"topic": "root"}),
                          ("too many links", {"message": "see http://a.b http://c.d http://e.f http://g.h now"}), ("a topic that is an array", {"topic[]": "x"})):
        fields = dict(good, token=token(), **change)
        if "topic[]" in change:
            fields.pop("topic")
        status, data = post(fields)
        check("refused: " + label, status == 422 and not data["ok"], (status, data))
        execute_limits()
    status, data = post(dict(good, token=token(), message="<script>alert(1)</script> and some words"))
    stored = query(target, "SELECT message FROM messages ORDER BY id DESC LIMIT 1")[0][0]
    check("a message with markup is stored as text", status == 200 and "<script>" in stored)
    execute_limits()
    status, data = post(dict(good, token=token()), headers={"Origin": "https://evil.example"})
    check("a post from another site is refused", status == 403, (status, data))
    execute_limits()
    codes = []
    for _ in range(7):
        codes.append(post(dict(good, token=token(wait=False)))[0])
    check("the sixth post in an hour is refused before its token is read", 429 in codes[5:] and codes[:5].count(429) == 0, codes)
    execute_limits()
    codes = [Client().request("GET", "/token.php")[0] for _ in range(32)]
    check("the token endpoint is limited per connection", 429 in codes and codes[:30].count(429) == 0, codes[28:])
    execute_limits()

    # --- the counter
    beacon = lambda body, headers=None, client=None: (client or Client()).request("POST", "/hit.php", headers=dict({"Content-Type": "text/plain"}, **(headers or {})), raw=body)
    hits = lambda: query(target, "SELECT COUNT(*) FROM hits")[0][0]
    check("GET on the counter is refused", Client().request("GET", "/hit.php")[0] == 405)
    status, _, _ = beacon(json.dumps({"p": "guide", "r": "https://www.google.com/search?q=x"}))
    row = query(target, "SELECT page, ref, device, visitor FROM hits")
    check("a view is counted with the host of the referrer only", status == 204 and len(row) == 1 and row[0][:3] == ("guide", "google.com", "desktop"), row)
    check("the visitor is a hash, not an address", row and "127.0.0.1" not in row[0][3] and len(row[0][3]) == 24)
    before = hits()
    beacon(json.dumps({"p": "home"}), {"DNT": "1"})
    check("Do Not Track: nothing counted", hits() == before)
    beacon(json.dumps({"p": "home"}), {"Sec-GPC": "1"})
    check("Global Privacy Control: nothing counted", hits() == before)
    beacon(json.dumps({"p": "home"}), {"User-Agent": "Googlebot/2.1"})
    check("a robot is not counted", hits() == before)
    beacon(json.dumps({"p": "../../etc/passwd"}))
    beacon(json.dumps({"p": "x" * 100}))
    check("a page that is not one of ours is not counted", hits() == before)
    check("a body that is not JSON is a 400", beacon("not json")[0] == 400)
    check("a body that is too big is refused", beacon(json.dumps({"p": "home", "r": "x" * 900}))[0] == 413)
    check("a beacon from another site is refused", beacon(json.dumps({"p": "home"}), {"Origin": "https://evil.example"})[0] == 403)
    execute_limits()
    codes = [beacon(json.dumps({"p": "faq"}))[0] for _ in range(62)]
    check("the counter is limited per connection", 429 in codes and codes[:60].count(429) == 0, codes[58:])
    execute_limits()

    # --- the download links
    status, headers, _ = Client().request("GET", "/go.php?to=github")
    check("the GitHub link redirects to the repository", status == 302 and headers.get("location", "").startswith("https://github.com/"), headers.get("location"))
    status, headers, _ = Client().request("GET", "/go.php?to=zip")
    check("the zip link redirects to the archive", status == 302 and headers.get("location", "").endswith(".zip"))
    status, headers, _ = Client().request("GET", "/go.php?to=https://evil.example")
    check("an address in the request is never followed", status == 404 and "location" not in headers)
    check("the clicks are counted", query(target, "SELECT target, COUNT(*) FROM downloads GROUP BY target ORDER BY target") == [("github", 1), ("zip", 1)])

    # --- the admin page
    admin = Client()
    status, headers, html = admin.request("GET", "/admin.php")
    check("the admin page asks for the key", status == 200 and 'name="key"' in html and "Dashboard" not in html)
    check("the key is posted, never put in an address", 'method="post"' in html and 'type="password"' in html)
    check("the admin page is not indexed or cached, and cannot be framed", "noindex" in headers.get("x-robots-tag", "") and "no-store" in headers.get("cache-control", "")
          and headers.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in headers.get("content-security-policy", ""))
    status, _, _ = admin.request("POST", "/admin.php", {"do": "login", "key": "wrong"})
    check("a wrong key is refused", status == 403)
    status, headers, _ = admin.request("POST", "/admin.php", {"do": "login", "key": KEY})
    check("the right key signs in", status == 303)
    status, _, html = admin.request("GET", "/admin.php")
    check("the dashboard shows the figures and the messages", status == 200 and "Dashboard" in html and "page views" in html and "Ada" in html)
    check("a message is printed as text", "&lt;script&gt;" in html and "<script>alert" not in html)
    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)
    status, _, _ = admin.request("POST", "/admin.php", {"do": "delete", "id": "1"})
    check("an action without the token is refused", status == 403 and query(target, "SELECT COUNT(*) FROM messages WHERE id = 1")[0][0] == 1)
    admin.request("POST", "/admin.php", {"do": "read", "id": "1", "csrf": csrf})
    check("with the token a message is marked read", query(target, "SELECT is_read FROM messages WHERE id = 1")[0][0] == 1)
    admin.request("POST", "/admin.php", {"do": "delete", "id": "1", "csrf": csrf})
    check("and deleted", query(target, "SELECT COUNT(*) FROM messages WHERE id = 1")[0][0] == 0)
    admin.request("POST", "/admin.php", {"do": "delete", "id": "1 OR 1=1", "csrf": csrf})
    check("an id that is not a number does nothing", query(target, "SELECT COUNT(*) FROM messages")[0][0] > 0)
    check("the range is taken from a fixed list", admin.request("GET", "/admin.php?days=90")[0] == 200)
    admin.request("POST", "/admin.php", {"do": "logout", "csrf": csrf})
    check("signing out ends the session", 'name="key"' in admin.request("GET", "/admin.php")[2])
    execute_limits()
    codes = [Client().request("POST", "/admin.php", {"do": "login", "key": "guess%d" % i})[0] for i in range(12)]
    check("the sign-in is limited: the eleventh attempt is refused", codes[:10].count(429) == 0 and 429 in codes[10:], codes)
    check("and even the right key waits once the limit is reached", Client().request("POST", "/admin.php", {"do": "login", "key": KEY})[0] == 429)

    # --- files
    for folder in ("data", "inc", "tests", "src"):
        text = open(os.path.join(target, folder, ".htaccess"), encoding="utf-8").read()
        check("a deny rule in " + folder + "/ for Apache 2.2 and 2.4", "Require all denied" in text and "Deny from all" in text)
    check("no real config is committed", not os.path.exists(os.path.join(SITE, "inc", "config.php")))
    check("the pages in the folder are the ones that the sources build", build_matches())

# ------------------------------------------------------------
def build_matches():
    before = {}
    for path in ("index.html", "guide/index.html", "faq/index.html", "contact/index.html", "404.html", "sitemap.xml", "robots.txt"):
        with open(os.path.join(SITE, path), encoding="utf-8") as handle:
            before[path] = handle.read()
    subprocess.run([sys.executable, os.path.join(os.path.dirname(SITE), "tools", "build_site.py")], capture_output=True, check=True)
    same = True
    for path, text in before.items():
        with open(os.path.join(SITE, path), encoding="utf-8") as handle:
            same = same and handle.read() == text
    return same

if __name__ == "__main__":
    main()
