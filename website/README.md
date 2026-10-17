# Karma Builder website

Four pages (home, user guide, FAQ, contact), a contact form and private statistics.

The pages are plain static HTML, built from the sources in `src/` and from `docs/index.html` of the repository. PHP 8.1 or later (with SQLite through PDO) only runs the parts that need a server: the contact form, the page counter, the download links and the admin page. No framework, no cookie on the public pages.

## What is in the folder

| Path | What it is |
|---|---|
| `index.html`, `guide/`, `faq/`, `contact/`, `404.html`, `sitemap.xml`, `robots.txt` | The built site. Do not edit these: run the build (below). |
| `src/` | The sources: `layout.html`, `pages/`, `faq.json`, `site.json`. Not served. |
| `token.php` | Gives the contact form a signed token (GET, no cookie). |
| `contact.php` | Takes the form (POST, answers in JSON). |
| `hit.php` | The page view counter, called by `assets/js/site.js` with a beacon. |
| `go.php` | Download links: counts a click, then redirects to a fixed target (`github`, `zip`). |
| `admin.php` | Private page: figures, download clicks, messages. The only page that sets a cookie. |
| `inc/` | `bootstrap.php` (settings, headers, token, session on demand), `db.php` (SQLite, rate limits), `contact.php`, `stats.php`. Not served. |
| `data/` | The SQLite file, created on the first request. Not served. |
| `tests/` | `smoke.py`, `attack.py`, `htaccess_check.py` and `router.php`. Not served. |

## Build

    python tools/build_site.py

It writes the pages, the sitemap and `robots.txt`, copies the screenshots of the guide to `assets/img/shots/`, and adds `?v=hash` to the CSS and the script so that a change is never hidden by a cache. Set `site_url` in `src/site.json` first, then run it again after a change of `src/`, of `docs/index.html` or of `SCRIPT_VERSION` of the tool, and upload the folder.

## Install

1. Copy the folder to the web server (Apache with `mod_headers`, `mod_setenvif`, `mod_rewrite` and `mod_expires`, PHP 8.1 or later with `pdo_sqlite` and `mbstring`).
2. Copy `inc/config.sample.php` to `inc/config.php` and fill it in. The file is in `.gitignore`: it never goes to the repository.
   * `salt`: `php -r 'echo bin2hex(random_bytes(32)), "\n";'` (the site refuses to start with less than 16 characters)
   * `admin_hash`: `php -r 'echo password_hash("a long passphrase", PASSWORD_DEFAULT), "\n";'`
   * `contact_to`: where the messages are mailed. It is never printed on the site.
   * `mail_from`: an address of the domain of the site, so that the mail passes SPF.
   * `data_dir` (optional): a folder outside the web root for the database, better than `data/`.
3. The web server user must be able to write in the data folder.
4. Open `/admin.php` and sign in with the passphrase.
5. In the server configuration, if you can: `TraceEnable Off`, `ServerTokens Prod`, `ServerSignature Off`. A `.htaccess` cannot close TRACE.

Without Apache, the rules of `.htaccess` have to be done in the configuration of the server: deny `data/`, `inc/`, `src/` and `tests/`, deny files that end in `.md .json .py .sql .sqlite .log .bak`, the 404 page, the headers, the refusal of the robots listed in it, and a limit of the size of a request body (about 64 kB).

## What is counted

Page views, with the day, the page, the host of the site the visitor came from, the kind of device, and a code that is a hash of the address and the browser with a secret and the day, so it cannot be followed from one day to the next. No cookie, no address stored. Nothing is counted for a browser that sends Do Not Track or Global Privacy Control, nor for robots (including AI crawlers and AI assistants). Download clicks are counted the same way, and only for a real click: not a HEAD, not a prefetch. Figures older than about 400 days are deleted from time to time.

## The contact form

The page asks `token.php` for a token when it opens: a time, a random value and an HMAC of both, made with the salt. No session, no cookie. Checks, in this order:

1. a limit per connection (5 posts an hour) and a limit for all connections together (60 an hour), taken before anything is read;
2. the size of the body (413 above 20 kB; Apache cuts at 64 kB);
3. where the post comes from (`Origin` or `Referer` must be the site itself);
4. the token: signature, age (a robot that answers in under 3 seconds is told it worked and nothing is kept; a token older than 2 hours is refused), and use once;
5. the hidden field (same answer as for a fast robot);
6. the fields: line breaks and control characters are taken out of the name and the address, the topic comes from a fixed list, a message with more than three links is refused;
7. the same text again within a day, from anywhere, is told it worked and stored once.

The message is stored first, then mailed: a mail server that is down loses nothing, and the admin page shows which messages were not mailed.

## Against robots, spam and AI

* AI robots and AI assistants are all refused: the crawlers that collect pages to train models and the assistants that fetch a page because a person asked (ChatGPT-User, Claude-User, Perplexity-User and others). They are in `robots.txt` (`Disallow: /`), in every page (`noai, noimageai`), and shut out by name in `.htaccess` (403), which does not depend on their good manners. `robots.txt` itself stays readable by everyone. The list is in `tools/build_site.py` (robots.txt) and in `.htaccess`; `attack.py` fails if the two differ. A person who pastes an address into an assistant gets nothing from the site, by choice.
* AI-written spam goes through the same gates as any other: limits, token, time on the page, hidden field, links, repeated text.
* The contact form is the only thing that writes. Everything printed in the admin page goes through `htmlspecialchars`. Every query is a prepared statement.

## Tests

    python website/tests/smoke.py        # pages, headers, form, counter, downloads, admin (77 checks)
    python website/tests/attack.py       # injection, markup, header injection, odd bodies, methods, file leaks, bursts, robots (50+ checks)
    python website/tests/htaccess_check.py http://127.0.0.1:8890   # the .htaccess on a real Apache

`smoke.py` and `attack.py` copy the site to a temporary folder and start the PHP built-in server (with a small router that stands in for `.htaccess`, and with several workers for the bursts). To run them on a real Apache copy of the site: `BSM_PORT=8890 BSM_DIR=/path/of/the/copy BSM_USER=www-data python website/tests/attack.py`. Never aim any of them at the live site.

## Updating the version

`TOOL_VERSION` is read from `SCRIPT_VERSION` of the tool by the build: nothing to edit here.
