<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : page view counter, called by assets/js/site.js with a beacon
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/db.php';
require __DIR__ . '/inc/stats.php';

// ------------------------------------------------------------
function done(int $status): never
{
    http_response_code($status);
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    exit;
}

// ------------------------------------------------------------
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    done(405);
}
// the limit comes before anything else is read
if (!rate_ok('hit:' . visitor_hash(false), 60, 60)) {
    done(429);
}
// a beacon of this site only: the browser says where it comes from
$site = strtolower((string)parse_url((string)cfg('site_url', ''), PHP_URL_HOST));
$own = strtolower((string)preg_replace('~:\d+$~', '', (string)($_SERVER['HTTP_HOST'] ?? '')));
$origin = strtolower((string)parse_url((string)($_SERVER['HTTP_ORIGIN'] ?? ''), PHP_URL_HOST));
if ($origin !== '' && !hash_equals($site, $origin) && !hash_equals($own, $origin)) {
    done(403);
}
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 600) {
    done(413);
}
$data = json_decode((string)file_get_contents('php://input', false, null, 0, 601), true);
if (!is_array($data) || !is_string($data['p'] ?? null) || (isset($data['r']) && !is_string($data['r']))) {
    done(400);
}
$page = $data['p'];
$referrer = substr((string)($data['r'] ?? ''), 0, 300);
try {
    record_hit($page, $referrer);
} catch (Throwable $error) {
    error_log('hit.php: ' . $error->getMessage());
}
done(204);
