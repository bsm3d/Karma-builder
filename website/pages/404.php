<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : page not found
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

page_head('404', 'Page not found', 'This page does not exist.');
?>
<section class="wrap narrow">
  <h1>Page not found</h1>
  <p class="lead">There is nothing at this address.</p>
  <p><a class="btn" href="<?= e(page_url('home')) ?>">Back to the home page</a></p>
</section>
<?php page_foot();
