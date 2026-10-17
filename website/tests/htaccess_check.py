# Karma Builder website
# Benoît Saint-Moulin | www.bsm3d.com
# Function : checks the .htaccess on a real Apache (headers, deny rules, 404 page, robots that train models, big bodies)
# PHP : not needed (Python 3 only)
# Version : 1.0.0
#
# usage: python website/tests/htaccess_check.py http://127.0.0.1:8890
# Aim it at a throwaway Apache that serves a copy of the folder (AllowOverride All, mod_php or php-fpm, mod_headers, mod_setenvif). Never at the live site.

import http.client
import re
import sys
import urllib.parse

results = []


# ------------------------------------------------------------
def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)[:200]) if detail != "" else ""))


# ------------------------------------------------------------
def repeated(base, path):
    parts = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=15)
    connection.request("GET", path, headers={"User-Agent": "Mozilla/5.0 Firefox/120.0"})
    response = connection.getresponse()
    response.read()
    names = [k.lower() for k, v in response.getheaders()]
    connection.close()
    return sorted(set(n for n in names if names.count(n) > 1 and n != "set-cookie"))


# ------------------------------------------------------------
def call(base, method, path, body=None, headers=None):
    parts = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=15)
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) Firefox/120.0")
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    text = response.read().decode("utf-8", "replace")
    reply = dict((k.lower(), v) for k, v in response.getheaders())
    connection.close()
    return response.status, reply, text


# ------------------------------------------------------------
def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8890"
    status, reply, text = call(base, "GET", "/")
    check("the home page is served", status == 200 and "Karma" in text, status)
    for name, word in (("x-content-type-options", "nosniff"), ("x-frame-options", "DENY"), ("referrer-policy", "strict-origin"), ("permissions-policy", "camera=()"),
                       ("content-security-policy", "frame-ancestors 'none'"), ("cross-origin-opener-policy", "same-origin"), ("cross-origin-resource-policy", "same-origin")):
        check("header " + name, word in reply.get(name, ""), reply.get(name))
    check("no HSTS over plain HTTP", "strict-transport-security" not in reply)
    check("the charset is UTF-8 in the header", "utf-8" in reply.get("content-type", "").lower(), reply.get("content-type"))
    check("no version of PHP in the headers", "x-powered-by" not in reply)
    status, reply, text = call(base, "GET", "/token.php")
    check("no version of PHP in the headers of an endpoint", "x-powered-by" not in reply and status == 200, reply.get("x-powered-by"))
    for path in ("/", "/guide/", "/nothing-here/", "/token.php", "/admin.php", "/assets/css/site.css"):
        check("no header is sent twice on " + path, not repeated(base, path), repeated(base, path))
    check("the endpoint keeps its headers and sets no cookie", "no-store" in reply.get("cache-control", "") and "set-cookie" not in reply and reply.get("x-content-type-options") == "nosniff")

    hidden = ["/inc/config.php", "/inc/bootstrap.php", "/inc/db.php", "/inc/", "/data/", "/data/.htaccess", "/src/layout.html", "/src/faq.json", "/src/site.json", "/tests/smoke.py",
              "/tests/attack.py", "/tests/router.php", "/.htaccess", "/README.md", "/inc/config.sample.php", "/%2e%2e/inc/config.php", "/assets/../inc/config.php",
              "/guide/../src/site.json", "/inc%2fconfig.php", "/.git/config", "/data/site.sqlite", "/x.bak", "/x.sql", "/x.log", "/x~"]
    for path in hidden:
        status, reply, text = call(base, "GET", path)
        check("not served: " + path, status in (400, 403, 404) and "<?php" not in text and "CREATE TABLE" not in text and "salt" not in text.lower(), status)
    status, reply, text = call(base, "GET", "/nothing-here/")
    check("an unknown page shows the 404 page with a 404", status == 404 and "Page not found" in text, status)
    status, reply, text = call(base, "GET", "/inc/config.php")
    check("a forbidden file shows the same page, not the server's", "Page not found" in text and "Apache" not in text, text[:80])
    check("a directory without index is not listed", call(base, "GET", "/assets/img/")[0] in (403, 404) and "Index of" not in call(base, "GET", "/assets/img/")[2])
    for path in ("/guide/", "/faq/", "/contact/"):
        status, reply, text = call(base, "GET", path)
        check("pretty address " + path, status == 200)
    check("a trailing-slash redirect stays on the site", call(base, "GET", "/guide")[1].get("location", "/").startswith(("/", base)), call(base, "GET", "/guide")[1].get("location"))

    for agent in ("GPTBot/1.0", "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", "CCBot/2.0 (https://commoncrawl.org/faq/)", "Bytespider; spider-feedback@bytedance.com",
                  "Mozilla/5.0 (compatible; Amazonbot/0.1)", "meta-externalagent/1.1", "Diffbot/0.1", "anthropic-ai", "cohere-ai", "PerplexityBot/1.0", "Scrapy/2.11", "Mozilla/5.0 AppleWebKit/537.36 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)",
                  "Claude-User/1.0", "Claude-SearchBot/1.0", "Perplexity-User/1.0", "OAI-SearchBot/1.0", "MistralAI-User/1.0", "DuckAssistBot/1.1"):
        status, reply, text = call(base, "GET", "/", headers={"User-Agent": agent})
        check("a training crawler is refused: " + agent[:40], status in (403, 404) and "Karma Builder" not in text.split("<title>")[-1][:0], status)
    for agent in ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                  "Mozilla/5.0 (compatible; bingbot/2.0)", "curl/8.0", "Mozilla/5.0 (X11) Firefox/120"):
        status, reply, text = call(base, "GET", "/", headers={"User-Agent": agent})
        check("not refused: " + agent[:40], status == 200, status)
    check("a training crawler can still read robots.txt to learn that it is not welcome", call(base, "GET", "/robots.txt", headers={"User-Agent": "GPTBot/1.0"})[0] == 200)

    status, reply, text = call(base, "POST", "/contact.php", "message=" + "a" * 70000, {"Content-Type": "application/x-www-form-urlencoded"})
    check("a body over the Apache limit is refused", status in (413, 400), status)
    status, reply, text = call(base, "POST", "/contact.php", "message=a", {"Content-Type": "application/x-www-form-urlencoded"})
    check("a small body reaches the form code", status in (400, 422, 429) and '"ok"' in text, (status, text[:80]))
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        status, reply, text = call(base, method, "/contact.php", "x=1")
        check(method + " is refused by the .htaccess", status in (403, 405), status)
    status, reply, text = call(base, "TRACE", "/")
    print("INFO TRACE answers %d (only TraceEnable Off in the server configuration closes it)" % status)
    status, reply, text = call(base, "GET", "/robots.txt")
    check("robots.txt is served as text", "text/plain" in reply.get("content-type", ""), reply.get("content-type"))
    check("static files are cached", "max-age" in call(base, "GET", "/assets/css/site.css")[1].get("cache-control", ""))
    print("\nRESULT:", "all %d checks passed" % len(results) if all(results) else "%d FAILED of %d" % (results.count(False), len(results)))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
