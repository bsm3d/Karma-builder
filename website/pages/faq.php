<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : frequently asked questions, one list that gives both the page and its structured data
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

$guide = page_url('guide');
$contact = page_url('contact');
$faq = [
    'General' => [
        ['what', 'What does BSM Karma Builder do?',
         'It builds and updates a complete Karma render setup in Houdini Solaris (LOPs): a camera, a sky or dome light, fog and clouds, a material library, render variables, Karma render settings and a USD Render ROP. You run it from a window inside Houdini and can run it as many times as you like.'],
        ['versions', 'Which Houdini versions does it support?',
         'Houdini 21 and 22, with Solaris and Karma. The tool uses the Houdini 22 parameter names and tries older names when they are missing. A parameter that your version does not have is skipped, and the Log tab says which one.'],
        ['licenses', 'Does it work with Houdini Apprentice, Indie and FX?',
         'It is a package of Python files that runs inside Houdini and is installed with a package file, so no license-specific asset file is involved. If you build the optional HDA yourself, build it with the Houdini license of the people who will open it: files saved with Indie or Apprentice cannot be opened by commercial licenses. I have not tested every Houdini tier.'],
        ['engines', 'Does it work with Karma CPU and Karma XPU?',
         'Yes, you choose the engine in the Scene tab. The volumetric atmosphere and the 2D clouds can behave differently in the two: if something does not show in one, try the other.'],
        ['safe', 'Will it change my scene or my nodes?',
         'Only the nodes it created. Each one carries a tag, and the tool never deletes, rewires, moves or retags a node without it. If one of your nodes already has the name of a tool node, the build stops with a message and leaves yours alone.'],
        ['offline', 'Does it send anything anywhere?',
         'No. The tool only uses the network when you press Download in the Materials tab (ambientCG, Poly Haven) or connect the AMD library, and nothing about you or your scene is sent.'],
    ],
    'License' => [
        ['license', 'Is it free?',
         'It is free for personal, educational and other noncommercial use under the PolyForm Noncommercial License 1.0.0, and the source is available. Using it in a studio, or on paid client work, needs a commercial license.'],
        ['students', 'I am a student or a teacher.',
         'Educational use is free. Use it for your coursework and your own projects.'],
        ['pro', 'I am a freelancer or I work in a studio.',
         'Work that is paid, or done inside a company, is commercial use. <a href="' . $contact . '">Write to me</a> with a few words about how you would use it and we find a license that fits.'],
        ['resell', 'Can I redistribute it, change it or sell it?',
         'You can change it for your own noncommercial use. You can pass on copies for noncommercial use if you keep the license text and the copyright notice. You cannot sell it, include it in a commercial product or service, or remove the author name.'],
        ['old', 'What about the old GPL versions?',
         'Versions published before 30 September 2026 were released under the GPL-3.0 and stay under it. Everything after is under the PolyForm Noncommercial License.'],
    ],
    'Install and use' => [
        ['no-menu', 'I installed it but I do not see the menu.',
         'Restart Houdini after Install.bat. The menu is <strong>BSM &rarr; Karma Builder</strong>, and the shelf <strong>BSM Karma</strong> is available from the <strong>+</strong> next to the shelf tabs. If nothing appears, check that the package file exists in the packages folder of the Houdini version you start. The <a href="' . $guide . '#install">guide</a> lists the folders.'],
        ['black', 'The sky is black with Volumetric Atmosphere.',
         'Check three things: the sun is above the horizon (a negative Solar Altitude is night), you look through the Karma viewport of the Export tab and not a standard viewport, and the camera sees far enough (the tool raises it for the camera it makes). The <a href="' . $guide . '#troubleshooting">troubleshooting table</a> has the details.'],
        ['freeze', 'Houdini freezes for a long time after a change.',
         'A running Karma viewport restarts when nodes are added or removed. Switch Live Update off, change what you need, then press Build Environment Only. Trying the CPU engine can also help on a heavy scene.'],
        ['debug', 'Where do I find the log to report a problem?',
         'In the Log tab: it shows every message, and <em>Open Folder</em> opens the folder of the debug log file. Send that file with your Houdini version through the <a href="' . $contact . '">contact page</a>.'],
        ['assign', 'A material was not assigned.',
         'The Log tab gives the reason: no prim selected, the file holds an expression, or the Material Linker of your version has another layout. Select prims in the list of the Materials tab or in the viewport, then assign again.'],
    ],
    'Privacy' => [
        ['privacy', 'Do you track visitors of this site?',
         'The visits are counted, without cookies and without storing your address: the count keeps the page, the day, the site you came from, and a code that is a hash of your address and browser mixed with a secret and the day, so it cannot be followed from one day to the next. Nothing is counted if your browser sends Do Not Track or Global Privacy Control, and robots are ignored. The contact form uses one session cookie to protect itself, and nothing else is set.'],
        ['messages', 'What happens to my message?',
         'It is stored on the server of this site and mailed to me, and it is used only to answer you. Ask me to delete it and I will.'],
    ],
];

// ------------------------------------------------------------
$entities = [];
foreach ($faq as $group) {
    foreach ($group as [$id, $question, $answer]) {
        $entities[] = ['@type' => 'Question', 'name' => $question, 'acceptedAnswer' => ['@type' => 'Answer', 'text' => trim(html_entity_decode(strip_tags($answer), ENT_QUOTES, 'UTF-8'))]];
    }
}
page_head('faq', 'FAQ', 'Answers about BSM Karma Builder: Houdini versions, license for students, freelancers and studios, installation problems, privacy.',
          [['@context' => 'https://schema.org', '@type' => 'FAQPage', 'mainEntity' => $entities]]);
?>
<div class="wrap narrow">
  <h1>FAQ</h1>
  <p class="lead">Short answers. The <a href="<?= e($guide) ?>">user guide</a> has the full detail, and the <a href="<?= e($contact) ?>">contact page</a> is the way to reach me.</p>
<?php foreach ($faq as $title => $group) : ?>
  <h2><?= e($title) ?></h2>
<?php foreach ($group as [$id, $question, $answer]) : ?>
  <details class="qa" id="<?= e($id) ?>">
    <summary><?= e($question) ?></summary>
    <p><?= $answer ?></p>
  </details>
<?php endforeach; ?>
<?php endforeach; ?>
  <p class="callout">Still stuck? <a href="<?= e($contact) ?>">Send me a message</a>.</p>
</div>
<?php page_foot();
