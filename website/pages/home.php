<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : home page
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

page_head('home', 'Home', 'BSM Karma Builder builds and updates a complete Karma render setup in Houdini Solaris: camera, sky, lights, materials, render settings. For Houdini 21 and 22.', [[
    '@context' => 'https://schema.org',
    '@type' => 'SoftwareApplication',
    'name' => SITE_NAME,
    'applicationCategory' => 'DeveloperApplication',
    'operatingSystem' => 'Windows, Linux, macOS (inside SideFX Houdini 21 and 22)',
    'softwareVersion' => TOOL_VERSION,
    'author' => ['@type' => 'Person', 'name' => 'Benoît Saint-Moulin', 'url' => 'https://www.bsm3d.com'],
    'description' => 'A tool for SideFX Houdini that builds and updates a Karma render setup in Solaris.',
]]);
?>
<section class="hero">
  <div class="wrap hero-grid">
    <div class="hero-text">
      <p class="eyebrow">For SideFX Houdini 21 and 22</p>
      <h1>A Karma render setup in one window</h1>
      <p class="lead">Camera, sky, lights, fog, clouds, materials, render variables and render settings: built in Solaris, then refined from the same window without losing what you did by hand.</p>
      <p class="actions">
        <a class="btn" href="/go.php?to=github" rel="noopener" target="_blank">Download</a>
        <a class="btn ghost" href="<?= e(page_url('guide')) ?>">Read the user guide</a>
      </p>
      <p class="muted small">Free for personal, educational and noncommercial use. <a href="<?= e(page_url('faq')) ?>#license">Studios and professional work: see the license</a>.</p>
    </div>
    <figure class="hero-shot">
      <img src="<?= e(asset('img/shots/scene.png')) ?>" alt="The Scene tab of the BSM Karma Builder window" width="600" height="443">
    </figure>
  </div>
</section>

<section class="wrap band">
  <h2>What it builds</h2>
  <p>One button creates the same chain you would wire by hand. Run it again and it updates its own nodes: nodes you made yourself are never touched.</p>
  <div class="chain" role="img" aria-label="The chain of nodes: camera, lighting, atmosphere, material library, linker, render variables, Karma settings, render ROP">
    <span>camera</span><i>&rarr;</i><span>sky or dome</span><i>&rarr;</i><span class="opt">fog</span><i>&rarr;</i><span class="opt">clouds</span><i>&rarr;</i><span>materials</span><i>&rarr;</i><span>AOVs</span><i>&rarr;</i><span>Karma settings</span><i>&rarr;</i><span>render ROP</span>
  </div>
</section>

<section class="wrap band">
  <h2>What you get</h2>
  <div class="cards">
    <article class="card"><h3>Four lighting setups</h3><p>Environment with a physical sky or an HDRI, Studio, 3 Points, and Interior with a window light and an optional view outside. Temperature and tint for every lamp.</p></article>
    <article class="card"><h3>Sky, fog and clouds</h3><p>Karma physical sky with presets, volumetric atmosphere, fog, 3D or fast 2D clouds, and a wind or drift that moves them with the time.</p></article>
    <article class="card"><h3>Materials without MaterialX nodes</h3><p>Sixteen basic materials, a general purpose PBR material with a texture set, random materials, and a simple editor for the everyday inputs.</p></article>
    <article class="card"><h3>Free material downloads</h3><p>Browse ambientCG and Poly Haven, drag a material onto a prim of the list or onto an object of the Solaris viewport.</p></article>
    <article class="card"><h3>Live update</h3><p>Move a slider and the render setup follows after a short pause. Changes that add or remove nodes wait for the Build button, so a running Karma viewport is not restarted for nothing.</p></article>
    <article class="card"><h3>Safe to run again</h3><p>Only the nodes it created carry its tag. Yours are never deleted, rewired or moved, and the tool says so when a name is already taken.</p></article>
  </div>
</section>

<section class="wrap band">
  <h2>In pictures</h2>
  <div class="shots">
    <figure><img src="<?= e(asset('img/shots/lighting.png')) ?>" alt="The Lighting tab" loading="lazy" width="600" height="880"><figcaption>Lighting: sky, HDRI, lamps</figcaption></figure>
    <figure><img src="<?= e(asset('img/shots/materials.png')) ?>" alt="The Materials tab with the catalog" loading="lazy" width="600" height="860"><figcaption>Materials: catalog and drag and drop</figcaption></figure>
    <figure><img src="<?= e(asset('img/shots/export.png')) ?>" alt="The Export tab with the viewport snapshots" loading="lazy" width="600" height="578"><figcaption>Export: snapshots and render buttons</figcaption></figure>
  </div>
</section>

<section class="wrap band two">
  <div>
    <h2>Requirements</h2>
    <ul>
      <li>SideFX Houdini 21 or 22, with Solaris (LOPs) and Karma.</li>
      <li>Nothing else to install: the interface only uses what ships with Houdini.</li>
      <li>Install by unpacking a folder and double-clicking <code>Install.bat</code> (Windows), or with a package file (Linux, macOS). The <a href="<?= e(page_url('guide')) ?>#install">guide</a> has the steps.</li>
    </ul>
  </div>
  <div>
    <h2>License</h2>
    <p>Published under the PolyForm Noncommercial License 1.0.0: free for personal, educational and other noncommercial use, with the source available. Using it in a studio or on paid work needs a commercial license. <a href="<?= e(page_url('contact')) ?>">Get in touch</a> to talk about it.</p>
  </div>
</section>

<section class="cta">
  <div class="wrap">
    <h2>Try it on your next render</h2>
    <p class="actions"><a class="btn" href="/go.php?to=github" rel="noopener" target="_blank">Download</a> <a class="btn ghost" href="<?= e(page_url('faq')) ?>">Read the FAQ</a></p>
  </div>
</section>
<?php page_foot();
