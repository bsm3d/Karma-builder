# BSM Karma Builder website

Four pages (home, user guide, FAQ, contact), a contact form and private statistics. Plain PHP 8.1 or later with SQLite (PDO), no framework, no build step.

## What is in the folder

| Path | What it is |
|---|---|
| `index.php` | Entry point. The page comes from `?pg=` and only the four known names are served. |
| `pages/` | `home.php`, `faq.php`, `contact.php`, `guide.php`, `404.php`. The guide reads two generated files, see below. |
| `inc/` | `bootstrap.php` (settings, security headers, session on demand), `db.php` (SQLite, rate limits), `stats.php` (what is counted), `layout.php` (head and footer). |
| `hit.php` | The page view counter, called by `assets/js/site.js` with a beacon. |
| `go.php` | Download links: counts the click, then redirects to a fixed target (`github`, `zip`). |
| `admin.php` | Private page: figures, download clicks, messages. |
| `data/` | The SQLite file, created on the first request. Never served. |
| `tests/` | `smoke.py`, functional tests on the PHP built-in server. |

## Install

1. Copy the folder to the web server (Apache with `mod_rewrite` and `mod_headers`, PHP 8.1 or later with `pdo_sqlite` and `mbstring`).
2. Copy `inc/config.sample.php` to `inc/config.php` and fill it in. The file is in `.gitignore`: it never goes to the repository.
   * `salt`: `php -r 'echo bin2hex(random_bytes(32)), "\n";'`
   * `admin_hash`: `php -r 'echo password_hash("a long passphrase", PASSWORD_DEFAULT), "\n";'`
   * `contact_to`: where the messages are mailed. It is never printed on the site.
   * `mail_from`: an address of the domain of the site, so that the mail passes SPF.
3. The web server user must be able to write in `data/`.
4. Open `/admin.php` and sign in with the passphrase.

Without Apache, the rewrite rules of `.htaccess` (`/guide`, `/faq`, `/contact`, `/sitemap.xml`) and its deny rules for `data/`, `inc/`, `pages/` and `tests/` have to be done in the configuration of the server. Set `pretty_urls` to `false` to use `?pg=` addresses.

## What is counted

Page views, with the day, the page, the host of the site the visitor came from, the kind of device, and a code that is a hash of the address and the browser with a secret and the day. No cookie, no address stored. Nothing is counted for a browser that sends Do Not Track or Global Privacy Control, nor for robots. Download clicks are counted the same way. Figures older than about 400 days are deleted from time to time.

The contact form uses one session cookie to protect itself (a token against forged posts). Nothing else sets a cookie.

## The contact form

Checks, in this order: a limit of five posts per hour and per connection (before the body is read), the token of the session, the hidden field and a minimum time on the page (a robot is told it worked and nothing is kept), then the fields. Line breaks are taken out of the name and the address, the topic comes from a fixed list, a message with more than three links is refused. The message is stored first, then mailed: a mail server that is down loses nothing, and the admin page shows which messages were not mailed.

## The user guide

It is built from `docs/index.html` of the repository, so that the documentation has one source:

    python tools/build_site_guide.py

It writes `pages/guide_content.inc.html` and `pages/guide_toc.inc.html`, and copies the screenshots to `assets/img/shots/`. Run it again after a change of the documentation, then upload the three places.

## Tests

    python website/tests/smoke.py

It copies the site to a temporary folder, starts the PHP built-in server, and checks every page, the headers, the form (token, honeypot, injected headers, limit), the counter (Do Not Track, robots, limits), the download links, the admin page (sign-in, limit, token on actions) and the HTML of the four pages. The built-in server ignores `.htaccess`: the deny rules are only read, test them on the real server (`/data/site.sqlite` and `/inc/config.php` must answer 403 or 404).

## Updating the version

`TOOL_VERSION` in `inc/bootstrap.php`, to match `SCRIPT_VERSION` of the tool.
