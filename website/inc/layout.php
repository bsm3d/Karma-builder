<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : the frame of every public page: head, header with the menu, footer
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

// ------------------------------------------------------------
function page_head(string $pg, string $title, string $description, array $extra_json_ld = []): void
{
    $full_title = $pg === 'home' ? SITE_NAME . ' | Karma render setup for Houdini' : $title . ' | ' . SITE_NAME;
    $canonical = rtrim((string)cfg('site_url', ''), '/') . ($pg === 'home' ? '/' : '/' . $pg);
    send_security_headers();
    header('Content-Type: text/html; charset=utf-8');
    $nav = ['home' => 'Home', 'guide' => 'User guide', 'faq' => 'FAQ', 'contact' => 'Contact'];
    ?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= e($full_title) ?></title>
<meta name="description" content="<?= e($description) ?>">
<link rel="canonical" href="<?= e($canonical) ?>">
<link rel="icon" type="image/png" href="<?= e(asset('img/favicon.png')) ?>">
<meta property="og:type" content="website">
<meta property="og:title" content="<?= e($full_title) ?>">
<meta property="og:description" content="<?= e($description) ?>">
<meta property="og:url" content="<?= e($canonical) ?>">
<meta property="og:image" content="<?= e(rtrim((string)cfg('site_url', ''), '/') . '/assets/img/shots/scene.png') ?>">
<meta name="theme-color" content="#d9622b">
<link rel="stylesheet" href="<?= e(asset('css/site.css')) ?>">
<?php foreach ($extra_json_ld as $block) : ?>
<script type="application/ld+json"><?= json_encode($block, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_AMP) ?></script>
<?php endforeach; ?>
</head>
<body data-page="<?= e($pg) ?>">
<a class="skip" href="#main">Skip to the content</a>
<header class="top">
  <div class="wrap bar">
    <a class="brand" href="<?= e(page_url('home')) ?>"><img src="<?= e(asset('img/logo.png')) ?>" alt="" width="38" height="40"><span><?= e(SITE_NAME) ?></span></a>
    <button class="menu-btn" type="button" aria-expanded="false" aria-controls="menu">Menu</button>
    <nav id="menu" class="menu" aria-label="Main">
<?php foreach ($nav as $key => $label) : ?>
      <a href="<?= e(page_url($key)) ?>"<?= $key === $pg ? ' aria-current="page"' : '' ?>><?= e($label) ?></a>
<?php endforeach; ?>
      <a class="btn small" href="/go.php?to=github" rel="noopener" target="_blank">Download</a>
    </nav>
  </div>
</header>
<main id="main">
<?php
}

// ------------------------------------------------------------
function page_foot(): void
{
    ?>
</main>
<footer class="foot">
  <div class="wrap foot-grid">
    <div>
      <strong><?= e(SITE_NAME) ?></strong> <?= e(TOOL_VERSION) ?><br>
      <span class="muted">A Karma render setup tool for SideFX Houdini 21 and 22.</span>
    </div>
    <div>
      <a href="<?= e(page_url('guide')) ?>">User guide</a> &middot; <a href="<?= e(page_url('faq')) ?>">FAQ</a> &middot;
      <a href="<?= e(page_url('contact')) ?>">Contact</a> &middot; <a href="<?= e((string)cfg('github_url', '#')) ?>" rel="noopener" target="_blank">GitHub</a>
    </div>
    <div class="muted">
      By <a href="https://www.bsm3d.com" rel="noopener" target="_blank">Benoît Saint-Moulin</a>.
      Visits are counted without cookies and without storing your address (<a href="<?= e(page_url('faq')) ?>#privacy">details</a>).
    </div>
  </div>
</footer>
<script src="<?= e(asset('js/site.js')) ?>" defer></script>
</body>
</html>
<?php
}
