<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : receives the contact form (a post from assets/js/site.js) and answers in JSON
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/db.php';
require __DIR__ . '/inc/contact.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    json_out(405, ['ok' => false, 'errors' => ['This address only takes the contact form.']]);
}
try {
    [$status, $data] = handle_contact();
} catch (Throwable $error) {
    error_log('contact.php: ' . $error->getMessage());
    [$status, $data] = [500, ['ok' => false, 'errors' => ['The message could not be saved. Please try again later.']]];
}
json_out($status, $data);
