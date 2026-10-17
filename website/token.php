<?php
// Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : gives the contact form its signed token (the pages are static files and cannot carry one)
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/db.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    json_out(405, ['ok' => false]);
}
if (!rate_ok('token:' . visitor_hash(false), 30, 60)) {
    json_out(429, ['ok' => false]);
}
json_out(200, ['ok' => true, 'token' => form_token_make()]);
