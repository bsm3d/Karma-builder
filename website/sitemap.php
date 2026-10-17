<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : sitemap.xml for the search engines (the .htaccess maps /sitemap.xml here)
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';

$base = rtrim((string)cfg('site_url', ''), '/');
header('Content-Type: application/xml; charset=utf-8');
echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<?php foreach (['' => 'weekly', 'guide' => 'weekly', 'faq' => 'monthly', 'contact' => 'yearly'] as $path => $frequency) : ?>
  <url><loc><?= e($base . '/' . $path) ?></loc><changefreq><?= $frequency ?></changefreq></url>
<?php endforeach; ?>
</urlset>
