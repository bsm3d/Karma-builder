<?php
// Router of the PHP built-in server for the tests: it does what the .htaccess does on Apache
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if (preg_match('~^/(guide|faq|contact)/?$~', $path, $m)) {
    $_GET['pg'] = $m[1];
    require __DIR__ . '/../index.php';
    return true;
}
if ($path === '/sitemap.xml') {
    require __DIR__ . '/../sitemap.php';
    return true;
}
return false;
