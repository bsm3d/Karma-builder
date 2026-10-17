<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : common start of every page: settings, security headers, session on demand, small helpers
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

const SITE_NAME = 'BSM Karma Builder';
const TOOL_VERSION = '1.0.0';
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

// ------------------------------------------------------------
function send_security_headers(bool $private = false): void
{
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Referrer-Policy: strict-origin-when-cross-origin');
    header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
    header("Content-Security-Policy: default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; "
         . "base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
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
function page_url(string $pg): string
{
    if ($pg === 'home') {
        return cfg('pretty_urls', true) ? '/' : 'index.php';
    }
    return cfg('pretty_urls', true) ? '/' . $pg : 'index.php?pg=' . $pg;
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
function go(string $location): never
{
    header('Location: ' . $location, true, 303);
    exit;
}
