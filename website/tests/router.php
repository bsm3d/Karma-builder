<?php
// Router of the PHP built-in server for the tests: it does what the .htaccess does on Apache
// (directory index, ErrorDocument 404, nothing served from the private folders, no source or data file)
$path = rawurldecode((string)parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH));
$root = realpath(__DIR__ . '/..');
if (strpos($path, "\0") !== false) {
    http_response_code(400);
    echo 'Bad request';
    return true;
}
$file = realpath($root . $path);
$relative = $file === false ? $path : substr($file, strlen($root));
if (($file !== false && $file !== $root && strncmp($file, $root . DIRECTORY_SEPARATOR, strlen($root) + 1) !== 0)) {
    http_response_code(400);
    echo 'Bad request';
    return true;
}
if (preg_match('~^/(inc|data|src|tests)(/|$)~', $relative) || preg_match('#(^|/)\.|~$|\.(bak|sql|sqlite|log|md|json|py|ini|sample|inc)$#i', $relative)) {
    http_response_code(403);
    header('Content-Type: text/html; charset=utf-8');
    readfile(__DIR__ . '/../404.html');
    return true;
}
if ($file !== false && (is_file($file) || is_file($file . '/index.html'))) {
    return false;
}
http_response_code(404);
header('Content-Type: text/html; charset=utf-8');
readfile(__DIR__ . '/../404.html');
return true;
