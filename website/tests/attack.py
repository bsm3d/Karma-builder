# BSM Karma Builder website
# Benoît Saint-Moulin | www.bsm3d.com
# Function : attack tests of the site: injection, XSS, header injection, odd bodies, bad methods, file leaks, bursts, robots, spam
# PHP : 8.1 and later (php on the path)
# Version : 1.0.0
#
# usage: python website/tests/attack.py
# A copy of the site runs on the PHP built-in server with several workers (a real burst needs them). Never aim this at the live site.
# On a real Apache copy: BSM_PORT=8890 BSM_DIR=/path/of/the/copy BSM_USER=www-data python website/tests/attack.py (the copy needs the config of smoke.prepare)

import concurrent.futures
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke
from smoke import KEY, PORT, SITE, check, execute, prepare, query, results


# ------------------------------------------------------------
def call(method, path, body=None, headers=None, cookie=""):
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) Firefox/120.0")
    if cookie:
        headers["Cookie"] = cookie
    if isinstance(body, dict):
        body = urllib.parse.urlencode(body)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    connection.request(method, path.replace(" ", "%20").replace("'", "%27"), body=body, headers=headers)
    response = connection.getresponse()
    data = response.read()
    reply = dict((k.lower(), v) for k, v in response.getheaders())
    cookies = [v for k, v in response.getheaders() if k.lower() == "set-cookie"]
    connection.close()
    return response.status, reply, cookies, data.decode("utf-8", "replace")


# ------------------------------------------------------------
# the last Set-Cookie of a name is the one that a browser keeps
def jar(cookies):
    kept = {}
    for value in cookies:
        name, _, rest = value.partition("=")
        kept[name] = rest.split(";")[0]
    return "; ".join("%s=%s" % item for item in kept.items())


# ------------------------------------------------------------
def fresh_token(wait=True):
    value = json.loads(call("GET", "/token.php")[3])["token"]
    if wait:
        time.sleep(3.2)
    return value


# ------------------------------------------------------------
def send(fields, headers=None, wait=True):
    fields = dict(fields)
    fields.setdefault("token", fresh_token(wait))
    status, reply, cookies, text = call("POST", "/contact.php", fields, headers)
    try:
        return status, json.loads(text)
    except ValueError:
        return status, {"raw": text}


# ------------------------------------------------------------
def main():
    work, target = smoke.prepare()
    environment = dict(os.environ, PHP_CLI_SERVER_WORKERS="8")
    server = None
    if smoke.OUTSIDE:
        target = smoke.OUTSIDE
    else:
        server = subprocess.Popen(["php", "-S", "127.0.0.1:%d" % PORT, "-t", target, os.path.join(target, "tests", "router.php")],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment)
    try:
        for _ in range(50):
            try:
                call("GET", "/")
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
    reset = lambda: execute(target, "DELETE FROM limits")
    messages = lambda: query(target, "SELECT COUNT(*) FROM messages")[0][0]
    tables = lambda: sorted(r[0] for r in query(target, "SELECT name FROM sqlite_master WHERE type='table'"))
    good = {"name": "Ada", "email": "ada@example.org", "topic": "bug", "message": "The sky stays black in my scene, Houdini 22.0.466."}
    call("GET", "/token.php")
    known = tables()

    # --- injection of SQL
    sqli = ["'; DROP TABLE messages; --", "\" OR \"1\"=\"1", "x' UNION SELECT name FROM sqlite_master --", "1; ATTACH DATABASE '/tmp/x' AS y; --"]
    for index, payload in enumerate(sqli):
        reset()
        status, data = send(dict(good, name=payload, message="Payload in the message: %s (%d)" % (payload, index)))
        check("SQL payload %d: stored as plain text or refused, never run" % index, status in (200, 422) and tables() == known, (status, data))
    rows = query(target, "SELECT name, message FROM messages")
    check("the payloads are in the table byte for byte", any(r[0] == sqli[0] for r in rows) and any(sqli[2] in r[1] for r in rows), rows[:2])
    reset()
    status, data = send(dict(good, email="a'; DROP TABLE messages;--@example.org"))
    check("a quote in the email address does not pass the validation", status == 422 and tables() == known)
    reset()
    for payload in ("home' OR '1'='1", "home;--", "guide\x00", "faq\nx"):
        call("POST", "/hit.php", json.dumps({"p": payload, "r": "https://x.example/'); DROP TABLE hits;--"}), {"Content-Type": "text/plain"})
    check("a page name with SQL in the counter is not counted, the tables stay", tables() == known and query(target, "SELECT COUNT(*) FROM hits WHERE page NOT IN ('home','guide','faq','contact')")[0][0] == 0)
    call("POST", "/hit.php", json.dumps({"p": "faq", "r": "https://a.example'--/p?q='"}), {"Content-Type": "text/plain"})
    check("a referrer with quotes keeps only a host", all(re.fullmatch(r"[a-z0-9.\-]*", row[0] or "") for row in query(target, "SELECT ref FROM hits")), query(target, "SELECT ref FROM hits"))
    status, _, _, _ = call("GET", "/go.php?to=github' OR '1'='1")
    check("a quote in the download target is a plain 404", status == 404)
    reset()
    admin = ""
    status, reply, cookies, _ = call("POST", "/admin.php", {"do": "login", "key": "' OR '1'='1"})
    check("an SQL payload as the admin key is just a wrong key", status == 403)

    # --- scripts and markup
    reset()
    markup = '<img src=x onerror=alert(1)><script>alert(2)</script>"><svg onload=alert(3)>'
    status, data = send(dict(good, name=markup, message="Markup test: " + markup))
    status, reply, cookies, html = call("POST", "/admin.php", {"do": "login", "key": KEY})
    cookie = jar(cookies)
    status, reply, _, html = call("GET", "/admin.php", cookie=cookie)
    check("markup of a visitor is printed as text in the admin page", status == 200 and "&lt;script&gt;" in html and "<script>alert" not in html and "<img src=x" not in html and "<svg onload" not in html)
    check("the admin page has no inline script for the CSP to allow", not re.search(r"<script(?![^>]*src=)", html))

    # --- line breaks, NUL and bad bytes
    reset()
    for label, fields in (
        ("a line break in the name", dict(good, name="Eve\r\nBcc: v@example.org\r\nSubject: hi")),
        ("a line break in the email", dict(good, email="a@b.com\nBcc: v@example.org")),
        ("an encoded line break in the email", dict(good, email="a@b.com%0d%0aBcc:v@example.org")),
        ("a NUL byte in the message", dict(good, message="before\x00after, long enough to pass")),
    ):
        status, data = send(fields)
        check("%s: no server error" % label, status in (200, 422), status)
    names = [r[0] for r in query(target, "SELECT name FROM messages")]
    check("no stored name holds a line break", not any("\n" in n or "\r" in n for n in names), names)
    check("no stored message holds a NUL byte", not any("\x00" in r[0] for r in query(target, "SELECT message FROM messages")))
    reset()
    raw = b"name=Ada&email=ada%40example.org&topic=bug&message=%ff%fe%fd+invalid+utf8+bytes+in+the+message&token=" + fresh_token().encode()
    status, reply, _, text = call("POST", "/contact.php", raw, {"Content-Type": "application/x-www-form-urlencoded"})
    check("bytes that are not UTF-8 give a clean answer, not a 500", status in (200, 422) and "Warning" not in text and "Fatal" not in text, (status, text[:120]))
    reset()
    status, data = send(dict(good, message="x" * 6000))
    stored = query(target, "SELECT MAX(LENGTH(message)) FROM messages")[0][0]
    check("a long message is cut to 5000 characters", status == 200 and stored <= 5000, (status, stored))
    reset()
    status, data = send(dict(good, message="y" * 30000))
    check("a body of 30 kB is refused with 413 before it is read", status == 413, (status, data))
    status, reply, _, text = call("POST", "/contact.php", "message=" + "z" * 3000000, {"Content-Type": "application/x-www-form-urlencoded"})
    check("a body of 3 MB is refused", status in (413, 400), status)
    reset()
    status, reply, _, text = call("POST", "/contact.php", '{"name":"x"}', {"Content-Type": "application/json"})
    check("a JSON body instead of a form is a clean refusal", status in (400, 422) and "Warning" not in text, (status, text[:100]))
    reset()
    status, reply, _, text = call("POST", "/contact.php", "name[]=a&email[]=b&topic[x]=1&message[]=c&token[]=d", {"Content-Type": "application/x-www-form-urlencoded"})
    check("arrays in place of strings are refused without an error", status in (400, 422) and "Warning" not in text and "TypeError" not in text, (status, text[:100]))

    # --- spam
    reset()
    before = messages()
    first = send(dict(good, message="A message that a robot sends again and again."))
    second = send(dict(good, message="A message that a robot sends again and again."))
    third = send(dict(good, message="A MESSAGE that a robot sends again and again."))
    check("the same text again is told 'ok' and stored once", first[0] == second[0] == third[0] == 200 and messages() == before + 1, (first, second, third))
    reset()
    before = messages()
    status, data = send(dict(good, message="Visit http://a.example http://b.example http://c.example http://d.example for gains"))
    check("a message full of links is refused", status == 422 and messages() == before)
    status, data = send(dict(good, _gotcha="yes", message="Honeypot filled in by a robot, long enough."))
    check("the honeypot silently drops the message", status == 200 and messages() == before)
    status, data = send(dict(good, message="Sent too quickly after the token was given."), wait=False)
    check("a form sent in under three seconds is silently dropped", status == 200 and messages() == before)

    # --- many connections at once
    reset()
    before = messages()
    tokens = [fresh_token(wait=False) for _ in range(12)]
    time.sleep(3.2)
    with concurrent.futures.ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda i: call("POST", "/contact.php", dict(good, token=tokens[i], message="Parallel message number %d from the burst test." % i))[0], range(12)))
    check("12 posts at the same time: no more than 5 pass the per-connection limit", codes.count(429) >= 7 and messages() - before <= 5, (codes, messages() - before))
    reset()
    before = messages()
    shared = fresh_token()
    with concurrent.futures.ThreadPoolExecutor(5) as pool:
        codes = list(pool.map(lambda i: call("POST", "/contact.php", dict(good, token=shared, message="One token used by five posts together, number %d." % i))[0], range(5)))
    check("one token in five posts at the same time: stored once", messages() - before == 1 and codes.count(400) == 4, (codes, messages() - before))
    reset()
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        codes = list(pool.map(lambda i: call("POST", "/admin.php", {"do": "login", "key": "guess%d" % i})[0], range(16)))
    check("16 wrong keys at the same time: the limit of 10 holds", codes.count(403) <= 10 and 429 in codes, sorted(codes))
    reset()
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        codes = list(pool.map(lambda i: call("GET", "/token.php")[0], range(60)))
    check("60 token requests at the same time: the limit of 30 holds", codes.count(200) <= 30, codes.count(200))
    reset()
    for index in range(61):
        execute(target, "INSERT INTO limits (bucket, ts) VALUES ('contact:everyone', ?)", (int(time.time()),))
    status, data = send(dict(good, message="Another connection while the whole form is saturated."))
    check("all connections together are capped: the 61st message of the hour is refused", status == 429 and "busy" in str(data), (status, data))
    reset()

    # --- methods, paths and files
    for path in ("/contact.php", "/token.php", "/hit.php", "/go.php?to=zip", "/admin.php"):
        for method in ("PUT", "DELETE", "PATCH", "TRACE"):
            status, _, _, text = call(method, path, "x=1")
            check("%s %s is not accepted" % (method, path), status in (400, 403, 404, 405, 413, 501) or (path == "/admin.php" and "Dashboard" not in text), status)
    status, _, _, text = call("GET", "/contact.php", headers={"X-HTTP-Method-Override": "POST"})
    check("a method override header is ignored", status == 405)
    leaks = ["/inc/config.php", "/inc/bootstrap.php", "/inc/db.php", "/data/", "/src/layout.html", "/src/faq.json", "/tests/smoke.py", "/tests/router.php",
             "/.git/config", "/.htaccess", "/README.md", "/../inc/config.php", "/%2e%2e/inc/config.php", "/..%2finc/config.php", "/assets/../inc/config.php",
             "/inc%2fconfig.php", "/inc/config.php%00.html", "/data/site.sqlite", "/guide/../src/site.json"]
    for path in leaks:
        status, _, _, text = call("GET", path)
        check("not served: %s" % path, status in (400, 403, 404) and "<?php" not in text and "salt" not in text.lower() and "CREATE TABLE" not in text, status)
    for path in ("/index.php", "/admin.php/x", "/contact.php/x", "/go.php/../inc/db.php"):
        status, _, _, text = call("GET", path)
        check("no information in the answer of %s" % path, "<?php" not in text and "Warning" not in text and "Notice" not in text and "Stack trace" not in text and "/home/" not in text, status)
    status, reply, _, text = call("GET", "/token.php")
    check("no version of PHP or the server in the headers", "x-powered-by" not in reply and "php" not in reply.get("server", "").lower().replace("development server", ""), reply.get("server"))
    status, reply, _, _ = call("OPTIONS", "/contact.php", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    check("no CORS: another site cannot read an answer", "access-control-allow-origin" not in reply)
    status, reply, _, _ = call("GET", "/token.php", headers={"Origin": "https://evil.example"})
    check("the token has no CORS header either", "access-control-allow-origin" not in reply)
    status, reply, _, text = call("GET", "/", headers={"Host": "evil.example"})
    check("the canonical address does not follow the Host header", "evil.example" not in text)
    status, reply, _, _ = call("GET", "/go.php?to=github", headers={"Host": "evil.example"})
    check("the download link does not follow the Host header", reply.get("location", "").startswith("https://github.com/"))
    status, reply, _, _ = call("GET", "/go.php?to=zip&url=https://evil.example&redirect=//evil.example")
    check("no extra parameter changes the destination", reply.get("location", "").startswith("https://github.com/") and "evil" not in reply.get("location", ""))

    # --- the session
    status, reply, cookies, _ = call("GET", "/admin.php")
    check("the admin session cookie is HttpOnly and SameSite=Strict", cookies and all("httponly" in c.lower() and "samesite=strict" in c.lower() for c in cookies), cookies)
    fixed = "bsmk_sid=aaaaaaaaaaaaaaaaaaaaaaaaaa"
    status, reply, cookies, _ = call("GET", "/admin.php", cookie=fixed)
    check("a session id chosen by an attacker is not taken", not cookies or "aaaaaaaaaaaaaaaaaaaaaaaaaa" not in "".join(cookies), cookies)
    reset()
    status, reply, cookies, _ = call("POST", "/admin.php", {"do": "login", "key": KEY}, cookie=fixed)
    check("after the sign-in the id is a new one", status == 303 and cookies and "aaaaaaaaaaaaaaaaaaaaaaaaaa" not in "".join(cookies), (status, cookies))
    signed_in = jar(cookies)
    status, reply, cookies, _ = call("GET", "/guide/")
    check("no cookie on a public page", not cookies)
    status, reply, cookies, _ = call("GET", "/admin.php?bsmk_sid=abcdefabcdefabcdefabcdef")
    check("an id in the address is not taken", "abcdefabcdefabcdefabcdef" not in "".join(cookies))
    count = messages()
    status, _, _, _ = call("POST", "/admin.php", {"do": "delete", "id": "1"}, headers={"Origin": "https://evil.example", "Referer": "https://evil.example/x"}, cookie=signed_in)
    check("a forged request from another site, with the admin's cookie but no token, is refused", status == 403 and messages() == count, status)
    status, _, _, _ = call("POST", "/admin.php", {"do": "delete", "id": "1", "csrf": "0" * 64}, cookie=signed_in)
    check("a made-up token is refused", status == 403 and messages() == count, status)

    # --- the counter against a flood and a forger
    reset()
    before = query(target, "SELECT COUNT(*) FROM hits")[0][0]
    for agent in ("curl/8.0", "python-requests/2.31", "Googlebot/2.1", "GPTBot/1.0", "ClaudeBot/1.0", "Bytespider", "ChatGPT-User/1.0", "Claude-User/1.0", "HeadlessChrome/120", "", "AhrefsBot/7.0"):
        call("POST", "/hit.php", json.dumps({"p": "home"}), {"Content-Type": "text/plain", "User-Agent": agent})
    check("tools, crawlers, AI robots and an empty agent are not counted", query(target, "SELECT COUNT(*) FROM hits")[0][0] == before)
    base = query(target, "SELECT COUNT(*) FROM downloads")[0][0]
    for agent in ("GPTBot/1.0", "ClaudeBot/1.0", "CCBot/2.0", "Bytespider", "ChatGPT-User/1.0", "Claude-User/1.0", "Perplexity-User/1.0"):
        call("GET", "/go.php?to=zip", headers={"User-Agent": agent})
    check("a robot or an assistant does not make the download count rise", query(target, "SELECT COUNT(*) FROM downloads")[0][0] == base)
    reset()
    call("GET", "/go.php?to=zip", headers={"Sec-Purpose": "prefetch"})
    call("HEAD", "/go.php?to=zip")
    check("a prefetch and a HEAD do not count as a download", query(target, "SELECT COUNT(*) FROM downloads")[0][0] == base)
    call("GET", "/go.php?to=zip")
    check("a click counts", query(target, "SELECT COUNT(*) FROM downloads")[0][0] == base + 1)

    # --- what robots and AI crawlers read
    robots = call("GET", "/robots.txt")[3]
    for name in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended", "Applebot-Extended", "Bytespider", "anthropic-ai", "PerplexityBot", "Amazonbot", "meta-externalagent"):
        check("robots.txt shuts out " + name, re.search(r"User-agent: %s\n(User-agent: .*\n)*Disallow: /\n" % re.escape(name), robots) is not None)
    check("robots.txt keeps the other robots out of the private addresses", "Disallow: /admin.php" in robots and "Disallow: /data/" in robots)
    for path in ("/", "/guide/", "/faq/", "/contact/", "/404.html"):
        html = call("GET", path)[3]
        check("%s says noai, and has a CSP in the page" % path, 'name="robots" content="' in html and "noai" in html and 'http-equiv="Content-Security-Policy"' in html)
    check("the 404 page is noindex", "noindex" in call("GET", "/404.html")[3])
    check("the page does not show an email address", not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", "".join(call("GET", p)[3] for p in ("/", "/guide/", "/faq/", "/contact/"))))
    htaccess = open(os.path.join(SITE, ".htaccess"), encoding="utf-8").read()
    for name in ("GPTBot", "ClaudeBot", "CCBot", "Bytespider", "Amazonbot", "meta-externalagent", "Diffbot"):
        check("the .htaccess blocks " + name, name in htaccess)
    check("the assistants that a person sends are not blocked by the .htaccess", not re.search(r"ChatGPT-User|Claude-User|Perplexity-User", htaccess))


if __name__ == "__main__":
    main()
