# BSM Karma Builder website
# Benoît Saint-Moulin | www.bsm3d.com
# Function : functional tests of the site: a copy of it runs on the PHP built-in server and every check is a real request
# PHP : 8.1 and later (php on the path)
# Version : 1.0.0
#
# usage: python website/tests/smoke.py
# The built-in server ignores .htaccess: the rewrite rules are done by tests/router.php, and the deny rules are only read, not tested.

import html.parser
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
PORT = 8765
KEY = "smoke-test-key"
results = []


# ------------------------------------------------------------
def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)[:200]) if detail != "" else ""))


# ------------------------------------------------------------
def prepare():
    work = tempfile.mkdtemp(prefix="bsm_site_")
    target = os.path.join(work, "site")
    shutil.copytree(SITE, target, ignore=shutil.ignore_patterns("config.php", "site.sqlite*", "__pycache__"))
    password_hash = subprocess.run(["php", "-r", "echo password_hash('%s', PASSWORD_DEFAULT);" % KEY], capture_output=True, text=True).stdout
    config = open(os.path.join(target, "inc", "config.sample.php"), encoding="utf-8").read()
    config = config.replace("'admin_hash'  => ''", "'admin_hash'  => '%s'" % password_hash).replace("'salt'        => ''", "'salt'        => 'test-salt'")
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
def query(target, sql, args=()):
    connection = sqlite3.connect(os.path.join(target, "data", "site.sqlite"))
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


# ------------------------------------------------------------
def execute(target, sql, args=()):
    connection = sqlite3.connect(os.path.join(target, "data", "site.sqlite"))
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
    for pg in ("home", "guide", "faq", "contact"):
        text = client.request("GET", "/index.php?pg=" + pg)[2]
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
                path = href.split("#")[0].split("?")[0]
                if path in ("/", "/guide", "/faq", "/contact", "/go.php"):
                    if "#" in href and path in ("/faq", "/guide"):
                        fragment = href.split("#")[1]
                        page_text = client.request("GET", path)[2]
                        if 'id="%s"' % fragment not in page_text:
                            problems.append("link to a missing section: " + href)
                    continue
                if not os.path.isfile(os.path.join(SITE, path.lstrip("/"))):
                    problems.append("broken local link: " + href)
        for src in parser.srcs:
            path = src.split("?")[0]
            if path.startswith("/") and not os.path.isfile(os.path.join(SITE, path.lstrip("/"))):
                problems.append("missing file: " + src)
        check("HTML of %s: balanced, unique ids, links and files resolve, images have alt" % pg, not problems, problems[:4])


# ------------------------------------------------------------
def main():
    work, target = prepare()
    server = subprocess.Popen(["php", "-S", "127.0.0.1:%d" % PORT, "-t", target, os.path.join(target, "tests", "router.php")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                Client().request("GET", "/")
                break
            except OSError:
                time.sleep(0.1)
        run(target)
    finally:
        server.terminate()
        server.wait(5)
        shutil.rmtree(work, ignore_errors=True)
    print("\nRESULT:", "all %d checks passed" % len(results) if all(results) else "%d FAILED of %d" % (results.count(False), len(results)))
    sys.exit(0 if all(results) else 1)


# ------------------------------------------------------------
def run(target):
    # --- the pages
    visitor = Client()
    for pg, word in (("home", "A Karma render setup in one window"), ("guide", "Quick start"), ("faq", "Is it free?"), ("contact", "Your message")):
        status, headers, html = visitor.request("GET", "/index.php?pg=" + pg)
        check("page %s answers 200 and has its content" % pg, status == 200 and word in html, status)
    for path in ("/guide", "/faq/", "/contact"):
        check("pretty address " + path, visitor.request("GET", path)[0] == 200)
    status, headers, html = visitor.request("GET", "/index.php?pg=nope")
    check("an unknown page is a 404", status == 404 and "Page not found" in html)
    check("a page name that is an array does not break", visitor.request("GET", "/index.php?pg[]=x")[0] in (200, 404))
    status, headers, html = Client().request("GET", "/")
    check("security headers are sent", headers.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in headers.get("content-security-policy", "") and headers.get("x-content-type-options") == "nosniff")
    reader = Client()
    for pg in ("home", "guide", "faq"):
        reader.request("GET", "/index.php?pg=" + pg)
    check("a visitor who only reads gets no cookie", not reader.cookies, reader.cookies)
    check("no inline style or script that the CSP would block", not re.search(r'<[^>]+ style="', html) and not re.search(r"<script(?![^>]*(src=|application/ld\+json))", html))
    guide_html = visitor.request("GET", "/guide")[2]
    check("the guide has its screenshots and no placeholder left", "{{assets}}" not in guide_html and "/assets/img/shots/scene.png" in guide_html)
    faq_html = visitor.request("GET", "/faq")[2]
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', faq_html, re.S)
    try:
        data = json.loads(blocks[0])
        check("the FAQ structured data is valid JSON with every question", data["@type"] == "FAQPage" and len(data["mainEntity"]) == faq_html.count('<details class="qa"'), len(data["mainEntity"]))
    except (IndexError, ValueError) as exc:
        check("the FAQ structured data is valid JSON", False, exc)
    status, headers, xml = visitor.request("GET", "/sitemap.xml")
    check("the sitemap is XML with the four pages", status == 200 and "xml" in headers.get("content-type", "") and xml.count("<loc>") == 4)

    audit_pages(visitor)

    # --- the contact form
    def fresh_form():
        client = Client()
        html = client.request("GET", "/contact")[2]
        return client, token_of(html)

    execute_limits = lambda: execute(target, "DELETE FROM limits")
    good = {"name": "Ada", "email": "ada@example.org", "topic": "bug", "message": "The sky stays black in my scene, Houdini 22.0.466."}
    client, token = fresh_form()
    check("the form carries a token and sets the session cookie", len(token) == 64 and "bsmk_sid" in client.cookies)
    status, _, html = client.request("POST", "/contact", dict(good, csrf=""))
    check("a post without the token is refused", status == 400 and "expired" in html, status)
    check("and nothing is stored", query(target, "SELECT COUNT(*) FROM messages")[0][0] == 0)
    status, _, _ = client.request("POST", "/contact", dict(good, csrf=token))
    check("a post a second after the page is a robot: told it worked, nothing kept", status == 303 and query(target, "SELECT COUNT(*) FROM messages")[0][0] == 0, status)
    client, token = fresh_form()
    time.sleep(3.2)
    status, headers, _ = client.request("POST", "/contact", dict(good, csrf=token))
    check("a good message is accepted and redirected", status == 303 and headers.get("location", "").endswith("/contact"), (status, headers.get("location")))
    status, _, html = client.request("GET", "/contact")
    check("the thanks are shown once", "Message sent" in html and "Message sent" not in client.request("GET", "/contact")[2])
    rows = query(target, "SELECT name, email, topic, message, mailed FROM messages")
    check("the message is in the database with its fields", len(rows) == 1 and rows[0][:3] == ("Ada", "ada@example.org", "bug"), rows)
    client, token = fresh_form()
    time.sleep(3.2)
    status, _, _ = client.request("POST", "/contact", dict(good, csrf=token, _gotcha="http://spam.example"))
    check("the honeypot: success is shown, nothing is kept", status == 303 and query(target, "SELECT COUNT(*) FROM messages")[0][0] == 1)
    client, token = fresh_form()
    time.sleep(3.2)
    status, _, html = client.request("POST", "/contact", dict(good, csrf=token, email="a@b.com\r\nBcc: victim@example.org"))
    check("a header injected through the email is refused", status == 422 and query(target, "SELECT COUNT(*) FROM messages")[0][0] == 1, status)
    check("the form keeps what was typed", "The sky stays black" in html and 'value="Ada"' in html)
    execute_limits()
    status, _, _ = client.request("POST", "/contact", dict(good, csrf=token, name="Eve\r\nBcc: victim@example.org"))
    name = query(target, "SELECT name FROM messages ORDER BY id DESC LIMIT 1")[0][0]
    check("line breaks of the name are taken out", status == 303 and name.startswith("Eve") and "\n" not in name and "\r" not in name, name)
    execute_limits()
    for label, change in (("an empty name", {"name": ""}), ("a short message", {"message": "hi"}), ("an unknown topic", {"topic": "root"}), ("too many links", {"message": "see http://a.b http://c.d http://e.f http://g.h now"})):
        client, token = fresh_form()
        time.sleep(3.1)
        status, _, html = client.request("POST", "/contact", dict(good, csrf=token, **change))
        check("refused: " + label, status == 422 and "was not sent" in html, status)
        execute_limits()
    client, token = fresh_form()
    time.sleep(3.1)
    status, _, html = client.request("POST", "/contact", dict(good, csrf=token, message="<script>alert(1)</script> and some words"))
    stored = query(target, "SELECT message FROM messages ORDER BY id DESC LIMIT 1")[0][0]
    check("a message with markup is stored as text", status == 303 and "<script>" in stored)
    execute_limits()
    codes = []
    for _ in range(7):
        client, token = fresh_form()
        codes.append(client.request("POST", "/contact", dict(good, csrf=token))[0])
    check("the sixth post in an hour is refused before it is read", 429 in codes[5:] and codes[:5].count(429) == 0, codes)
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
    status, _, html = admin.request("GET", "/admin.php")
    check("the admin page asks for the key", status == 200 and 'name="key"' in html and "Dashboard" not in html)
    check("the key is posted, never put in an address", 'method="post"' in html and 'type="password"' in html)
    status, headers, _ = admin.request("GET", "/admin.php")
    check("the admin page is not indexed or cached", "noindex" in headers.get("x-robots-tag", "") and "no-store" in headers.get("cache-control", ""))
    status, _, _ = admin.request("POST", "/admin.php", {"do": "login", "key": "wrong"})
    check("a wrong key is refused", status == 403)
    status, headers, _ = admin.request("POST", "/admin.php", {"do": "login", "key": KEY})
    check("the right key signs in", status == 303)
    status, _, html = admin.request("GET", "/admin.php")
    check("the dashboard shows the figures and the messages", status == 200 and "Dashboard" in html and "page views" in html and "Ada" in html)
    check("a message is printed as text", "&lt;script&gt;" in html and "<script>alert" not in html)
    token = token_of(html)
    status, _, _ = admin.request("POST", "/admin.php", {"do": "delete", "id": "1"})
    check("an action without the token is refused", status == 403 and query(target, "SELECT COUNT(*) FROM messages WHERE id = 1")[0][0] == 1)
    admin.request("POST", "/admin.php", {"do": "read", "id": "1", "csrf": token})
    check("with the token a message is marked read", query(target, "SELECT is_read FROM messages WHERE id = 1")[0][0] == 1)
    admin.request("POST", "/admin.php", {"do": "delete", "id": "1", "csrf": token})
    check("and deleted", query(target, "SELECT COUNT(*) FROM messages WHERE id = 1")[0][0] == 0)
    admin.request("POST", "/admin.php", {"do": "delete", "id": "1 OR 1=1", "csrf": token})
    check("an id that is not a number does nothing", query(target, "SELECT COUNT(*) FROM messages")[0][0] > 0)
    status, _, _ = admin.request("GET", "/admin.php?days=90")
    check("the range is taken from a fixed list", status == 200)
    admin.request("POST", "/admin.php", {"do": "logout", "csrf": token})
    status, _, html = admin.request("GET", "/admin.php")
    check("signing out ends the session", 'name="key"' in html)
    execute_limits()
    codes = [Client().request("POST", "/admin.php", {"do": "login", "key": "guess%d" % i})[0] for i in range(12)]
    check("the sign-in is limited: the eleventh attempt is refused", codes[:10].count(429) == 0 and 429 in codes[10:], codes)
    status, _, _ = Client().request("POST", "/admin.php", {"do": "login", "key": KEY})
    check("and even the right key waits once the limit is reached", status == 429, status)

    # --- files
    for folder in ("data", "inc", "pages", "tests"):
        text = open(os.path.join(target, folder, ".htaccess"), encoding="utf-8").read()
        check("a deny rule in " + folder + "/ for Apache 2.2 and 2.4", "Require all denied" in text and "Deny from all" in text)
    check("no real config is committed", not os.path.exists(os.path.join(SITE, "inc", "config.php")))


if __name__ == "__main__":
    main()
