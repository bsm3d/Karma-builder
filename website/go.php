<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : counts a click on a download link, then sends the visitor on (a fixed list of targets, never an address from the request)
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/db.php';
require __DIR__ . '/inc/stats.php';

// ------------------------------------------------------------
$repo = rtrim((string)cfg('github_url', 'https://github.com/bsm3d/Karma-builder'), '/');
$target = isset($_GET['to']) && is_string($_GET['to']) ? $_GET['to'] : '';

switch ($target) {
    case 'github': $destination = $repo;                                  break;
    case 'zip':    $destination = $repo . '/archive/refs/heads/main.zip'; break;
    default:
        http_response_code(404);
        header('Content-Type: text/plain; charset=utf-8');
        exit('Unknown link.');
}

// the counter must never be the reason a download fails
try {
    if (rate_ok('go:' . visitor_hash(false), 30, 60)) {
        record_download($target);
    }
} catch (Throwable $error) {
    error_log('go.php: ' . $error->getMessage());
}
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('Location: ' . $destination, true, 302);
exit;
