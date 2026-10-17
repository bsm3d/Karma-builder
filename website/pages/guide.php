<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : user guide, built from the documentation of the repository (tools/build_site_guide.py)
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

page_head('guide', 'User guide', 'How to install and use BSM Karma Builder in Houdini: quick start, what gets built, every tab of the window, presets, troubleshooting.');
$toc = is_file(__DIR__ . '/guide_toc.inc.html') ? (string)file_get_contents(__DIR__ . '/guide_toc.inc.html') : '';
$content = is_file(__DIR__ . '/guide_content.inc.html') ? (string)file_get_contents(__DIR__ . '/guide_content.inc.html') : '<p>The guide is not built yet.</p>';
$content = str_replace('{{assets}}', '/assets', $content);
?>
<div class="wrap guide">
  <nav class="toc" aria-label="Table of contents"><?= $toc ?></nav>
  <article class="doc">
    <h1>User guide</h1>
    <p class="lead">Version <?= e(TOOL_VERSION) ?>, for Houdini 21 and 22. Something not here? Try the <a href="<?= e(page_url('faq')) ?>">FAQ</a> or <a href="<?= e(page_url('contact')) ?>">write to me</a>.</p>
<?= $content ?>
  </article>
</div>
<?php page_foot();
