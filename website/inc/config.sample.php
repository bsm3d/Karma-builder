<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : settings of the site. Copy this file to config.php (never committed) and fill it in
// PHP : 8.1 and later (PDO SQLite)
// Version : 1.0.0

return [
    'site_url'    => 'https://karma.example.com',   // no trailing slash, used for canonical links and the sitemap
    'github_url'  => 'https://github.com/bsm3d/Karma-builder',
    'contact_to'  => 'you@example.com',             // where the messages are mailed, never printed on the site
    'mail_from'   => 'no-reply@example.com',        // an address of the domain of the site (SPF), not the visitor's
    // php -r 'echo password_hash("a long passphrase", PASSWORD_DEFAULT), "\n";'
    'admin_hash'  => '',
    // php -r 'echo bin2hex(random_bytes(32)), "\n";'
    'salt'        => '',
    'pretty_urls' => true,                          // /guide instead of ?pg=guide, needs the .htaccess of this folder (Apache)
    'trust_proxy' => false,                         // true only behind a reverse proxy that sets X-Forwarded-For
    'timezone'    => 'Europe/Paris',
];
