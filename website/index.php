<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : entry point, the pages go through an explicit whitelist
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/db.php';
require __DIR__ . '/inc/stats.php';
require __DIR__ . '/inc/layout.php';

// ------------------------------------------------------------
$pg = isset($_GET['pg']) && is_string($_GET['pg']) ? $_GET['pg'] : 'home';

switch ($pg) {
    case 'home':    require __DIR__ . '/pages/home.php';    break;
    case 'guide':   require __DIR__ . '/pages/guide.php';   break;
    case 'faq':     require __DIR__ . '/pages/faq.php';     break;
    case 'contact': require __DIR__ . '/pages/contact.php'; break;
    default:
        http_response_code(404);
        require __DIR__ . '/pages/404.php';
        break;
}
