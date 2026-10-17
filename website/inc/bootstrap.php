<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : common start of every page: settings, security headers, session on demand, small helpers
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

const SITE_NAME = 'BSM Karma Builder';
const SESSION_NAME = 'bsmk_sid';

// ------------------------------------------------------------
$config_file = __DIR__ . '/config.php';
if (!is_file($config_file)) {
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    exit('The site is not configured yet: copy inc/config.sample.php to inc/config.php.');
}
$CONFIG = require $config_file;
date_default_timezone_set($CONFIG['timezone'] ?? 'UTC');
ini_set('display_errors', '0');
ini_set('expose_php', '0');
header_remove('X-Powered-By');
// the salt makes the visitor codes and the form tokens impossible to guess: an empty one would make them worthless
if (strlen((string)($CONFIG['salt'] ?? '')) < 16) {
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    exit('The site is not configured yet: set a salt of at least 16 characters in inc/config.php.');
}

// ------------------------------------------------------------
function send_security_headers(bool $private = false): void
{
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Referrer-Policy: strict-origin-when-cross-origin');
    header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
    header("Content-Security-Policy: default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; "
         . "base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
    header('Cross-Origin-Opener-Policy: same-origin');
    header('Cross-Origin-Resource-Policy: same-origin');
    if (is_https()) {
        header('Strict-Transport-Security: max-age=31536000');
    }
    if ($private) {
        header('Cache-Control: no-store');
        header('X-Robots-Tag: noindex, nofollow');
    }
}

// ------------------------------------------------------------
function e(?string $text): string
{
    return htmlspecialchars((string)$text, ENT_QUOTES, 'UTF-8');
}

// ------------------------------------------------------------
function cfg(string $key, $default = null)
{
    global $CONFIG;
    return $CONFIG[$key] ?? $default;
}

// ------------------------------------------------------------
function is_https(): bool
{
    return (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || (int)($_SERVER['SERVER_PORT'] ?? 0) === 443;
}

// ------------------------------------------------------------
function asset(string $path): string
{
    $file = __DIR__ . '/../assets/' . $path;
    $version = is_file($file) ? (string)filemtime($file) : '0';
    return '/assets/' . $path . '?v=' . $version;
}

// ------------------------------------------------------------
// The session is started only where it is needed (the contact form, the admin): a visitor who only reads gets no cookie.
function session_boot(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    // a session id that the server did not make is not taken, and an id never travels in an address
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    ini_set('session.use_trans_sid', '0');
    session_name(SESSION_NAME);
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'secure'   => is_https(),
        'httponly' => true,
        'samesite' => 'Strict',
    ]);
    session_start();
}

// ------------------------------------------------------------
function csrf_token(): string
{
    session_boot();
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(32));
    }
    return $_SESSION['csrf'];
}

// ------------------------------------------------------------
function csrf_ok(?string $sent): bool
{
    session_boot();
    return is_string($sent) && !empty($_SESSION['csrf']) && hash_equals($_SESSION['csrf'], $sent);
}

// ------------------------------------------------------------
function client_ip(): string
{
    $ip = $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
    if (cfg('trust_proxy', false) && !empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
        $first = trim(explode(',', $_SERVER['HTTP_X_FORWARDED_FOR'])[0]);
        if (filter_var($first, FILTER_VALIDATE_IP)) {
            $ip = $first;
        }
    }
    return $ip;
}

// ------------------------------------------------------------
// Never the address itself in the database: a hash that changes every day, so a visitor cannot be followed from one day to the next.
function visitor_hash(bool $daily = true): string
{
    $agent = substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 200);
    $day = $daily ? date('Y-m-d') : 'limit';
    return substr(hash('sha256', cfg('salt', '') . '|' . $day . '|' . client_ip() . '|' . ($daily ? $agent : '')), 0, 24);
}

// ------------------------------------------------------------
function wants_privacy(): bool
{
    return ($_SERVER['HTTP_DNT'] ?? '') === '1' || ($_SERVER['HTTP_SEC_GPC'] ?? '') === '1';
}

// ------------------------------------------------------------
// The pages are static files, so the form has no session to hold a token: the token is signed (HMAC with the salt), carries the
// time it was made, and is used up when a message is stored.
function form_token_make(): string
{
    $payload = time() . '.' . bin2hex(random_bytes(8));
    return $payload . '.' . substr(hash_hmac('sha256', $payload, (string)cfg('salt')), 0, 32);
}

// ------------------------------------------------------------
// 'ok', 'bad' (not ours), 'early' (a robot is quicker than a person), 'expired', 'used'
function form_token_check(string $token): string
{
    $parts = explode('.', $token);
    if (count($parts) !== 3 || !ctype_digit($parts[0]) || !ctype_xdigit($parts[1]) || !ctype_xdigit($parts[2])) {
        return 'bad';
    }
    [$made, $nonce, $signature] = $parts;
    $expected = substr(hash_hmac('sha256', $made . '.' . $nonce, (string)cfg('salt')), 0, 32);
    if (!hash_equals($expected, $signature)) {
        return 'bad';
    }
    $age = time() - (int)$made;
    if ($age < 0 || $age > 7200) {
        return 'expired';
    }
    if ($age < 3) {
        return 'early';
    }
    return rate_count('nonce:' . $nonce, 7200) > 0 ? 'used' : 'ok';
}

// ------------------------------------------------------------
// true for the one request that gets to use the token: two posts that arrive together cannot both have it
function form_token_use(string $token): bool
{
    $nonce = explode('.', $token)[1] ?? '';
    return rate_ok('nonce:' . $nonce, 1, 7200);
}

// ------------------------------------------------------------
function json_out(int $status, array $data): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

// ------------------------------------------------------------
// A request that a browser sends from a page of this site: the Origin says so. A request with no Origin (a tool) passes this test,
// the token and the limits are what protect the endpoint.
function same_site_request(): bool
{
    $origin = strtolower((string)parse_url((string)($_SERVER['HTTP_ORIGIN'] ?? ''), PHP_URL_HOST));
    if ($origin === '') {
        $fetch_site = $_SERVER['HTTP_SEC_FETCH_SITE'] ?? '';
        return $fetch_site === '' || $fetch_site === 'same-origin' || $fetch_site === 'none';
    }
    $site = strtolower((string)parse_url((string)cfg('site_url', ''), PHP_URL_HOST));
    $own = strtolower((string)preg_replace('~:\d+$~', '', (string)($_SERVER['HTTP_HOST'] ?? '')));
    return hash_equals($site, $origin) || hash_equals($own, $origin);
}

// ------------------------------------------------------------
// A form is a few kilobytes: a bigger body is refused before anything is read from it.
function body_too_big(int $limit = 20000): bool
{
    return (int)($_SERVER['CONTENT_LENGTH'] ?? 0) > $limit;
}

// ------------------------------------------------------------
function go(string $location): never
{
    header('Location: ' . $location, true, 303);
    exit;
}
