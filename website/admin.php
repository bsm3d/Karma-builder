<?php
// Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : private page for the owner: statistics, download clicks and the messages of the contact form
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/db.php';
require __DIR__ . '/inc/stats.php';
require __DIR__ . '/inc/contact.php';

const ADMIN_SESSION_SECONDS = 7200;
const LOGIN_ATTEMPTS = 10;
const LOGIN_WINDOW = 900;

send_security_headers(true);
header('Content-Type: text/html; charset=utf-8');
session_boot();

// ------------------------------------------------------------
function admin_in(): bool
{
    return isset($_SESSION['admin_until']) && (int)$_SESSION['admin_until'] > time();
}

// ------------------------------------------------------------
function admin_head(string $title): void
{
    ?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title><?= e($title) ?> | <?= e(SITE_NAME) ?></title>
<link rel="stylesheet" href="<?= e(asset('css/site.css')) ?>">
</head>
<body class="admin">
<main class="wrap">
<?php
}

// ------------------------------------------------------------
function admin_foot(): void
{
    ?>
</main>
</body>
</html>
<?php
}

// ------------------------------------------------------------
$error = '';
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $do = is_string($_POST['do'] ?? null) ? $_POST['do'] : '';
    if ($do === 'login') {
        // the key is never put in a URL: a form that posts, with a limit on the attempts. The limit is checked first.
        if (!rate_ok('login:' . visitor_hash(false), LOGIN_ATTEMPTS, LOGIN_WINDOW)) {
            http_response_code(429);
            $error = 'Too many attempts. Try again later.';
        } else {
            $hash = (string)cfg('admin_hash', '');
            $key = is_string($_POST['key'] ?? null) ? $_POST['key'] : '';
            if ($hash !== '' && $key !== '' && strlen($key) < 500 && password_verify($key, $hash)) {
                session_regenerate_id(true);
                $_SESSION['admin_until'] = time() + ADMIN_SESSION_SECONDS;
                csrf_token();
                rate_reset('login:' . visitor_hash(false));
                go('admin.php');
            }
            http_response_code(403);
            $error = 'Wrong key.';
        }
    } elseif (admin_in()) {
        // every action that changes something carries the token of the session
        if (!csrf_ok($_POST['csrf'] ?? null)) {
            http_response_code(403);
            exit('The page expired. Reload it.');
        }
        $id = filter_var($_POST['id'] ?? null, FILTER_VALIDATE_INT);
        switch ($do) {
            case 'logout':
                $_SESSION = [];
                session_destroy();
                go('admin.php');
            case 'read':
            case 'unread':
                if ($id !== false) {
                    db()->prepare('UPDATE messages SET is_read = ? WHERE id = ?')->execute([$do === 'read' ? 1 : 0, $id]);
                }
                break;
            case 'delete':
                if ($id !== false) {
                    db()->prepare('DELETE FROM messages WHERE id = ?')->execute([$id]);
                }
                break;
        }
        go('admin.php' . (isset($_GET['days']) ? '?days=' . (int)$_GET['days'] : ''));
    }
}

// ------------------------------------------------------------
if (!admin_in()) {
    admin_head('Sign in');
    ?>
<section class="narrow">
  <h1>Sign in</h1>
<?php if ($error !== '') : ?>
  <div class="callout warn" role="alert"><?= e($error) ?></div>
<?php endif; ?>
<?php if ((string)cfg('admin_hash', '') === '') : ?>
  <div class="callout warn">No admin key is set: put a password hash in inc/config.php (see config.sample.php).</div>
<?php endif; ?>
  <form class="form" method="post" action="admin.php">
    <input type="hidden" name="do" value="login">
    <label for="key">Key</label>
    <input id="key" name="key" type="password" autocomplete="current-password" required>
    <button class="btn" type="submit">Sign in</button>
  </form>
</section>
<?php
    admin_foot();
    exit;
}

// ------------------------------------------------------------
$days = isset($_GET['days']) && in_array((int)$_GET['days'], [7, 30, 90], true) ? (int)$_GET['days'] : 30;
$report = stats_report($days);
$max_views = 1;
foreach ($report['per_day'] as $row) {
    $max_views = max($max_views, (int)$row['views']);
}
$messages = db()->query('SELECT id, ts, name, email, topic, message, is_read, mailed FROM messages ORDER BY id DESC LIMIT 60')->fetchAll();
$unread = (int)db()->query('SELECT COUNT(*) FROM messages WHERE is_read = 0')->fetchColumn();
$token = csrf_token();

admin_head('Dashboard');
?>
<h1>Dashboard</h1>
<form class="inline" method="post" action="admin.php"><input type="hidden" name="do" value="logout"><input type="hidden" name="csrf" value="<?= e($token) ?>"><button class="btn small ghost" type="submit">Sign out</button></form>
<p>
<?php foreach ([7, 30, 90] as $range) : ?>
  <a class="btn small<?= $range === $days ? '' : ' ghost' ?>" href="admin.php?days=<?= $range ?>"><?= $range ?> days</a>
<?php endforeach; ?>
</p>
<div class="figures">
  <div><strong><?= (int)$report['total']['views'] ?></strong><span>page views</span></div>
  <div><strong><?= (int)$report['total']['visits'] ?></strong><span>visits (one per visitor and day)</span></div>
  <div><strong><?= array_sum(array_column($report['downloads'], 'clicks')) ?></strong><span>download clicks</span></div>
  <div><strong><?= $unread ?></strong><span>unread messages</span></div>
</div>

<h2>Per day</h2>
<table>
  <tr><th>Day</th><th>Views</th><th>Visitors</th><th>Views</th></tr>
<?php foreach ($report['per_day'] as $row) : ?>
  <tr><td><?= e($row['day']) ?></td><td><?= (int)$row['views'] ?></td><td><?= (int)$row['visitors'] ?></td><td><meter min="0" max="<?= $max_views ?>" value="<?= (int)$row['views'] ?>"></meter></td></tr>
<?php endforeach; ?>
<?php if (!$report['per_day']) : ?>
  <tr><td colspan="4">Nothing counted yet.</td></tr>
<?php endif; ?>
</table>

<div class="two">
  <div><h2>Pages</h2><table><tr><th>Page</th><th>Views</th></tr>
<?php foreach ($report['pages'] as $row) : ?><tr><td><?= e($row['page']) ?></td><td><?= (int)$row['views'] ?></td></tr><?php endforeach; ?>
  </table></div>
  <div><h2>Coming from</h2><table><tr><th>Site</th><th>Views</th></tr>
<?php foreach ($report['referrers'] as $row) : ?><tr><td><?= e($row['ref']) ?></td><td><?= (int)$row['views'] ?></td></tr><?php endforeach; ?>
  </table></div>
  <div><h2>Devices</h2><table><tr><th>Device</th><th>Views</th></tr>
<?php foreach ($report['devices'] as $row) : ?><tr><td><?= e($row['device']) ?></td><td><?= (int)$row['views'] ?></td></tr><?php endforeach; ?>
  </table></div>
  <div><h2>Downloads</h2><table><tr><th>Link</th><th>Clicks</th></tr>
<?php foreach ($report['downloads'] as $row) : ?><tr><td><?= e($row['target']) ?></td><td><?= (int)$row['clicks'] ?></td></tr><?php endforeach; ?>
  </table></div>
</div>

<h2>Messages</h2>
<?php foreach ($messages as $m) : ?>
<article class="message<?= $m['is_read'] ? '' : ' new' ?>">
  <header>
    <strong><?= e($m['name']) ?></strong> &lt;<?= e($m['email']) ?>&gt; &middot; <?= e(TOPICS[$m['topic']] ?? $m['topic']) ?> &middot; <?= e(date('Y-m-d H:i', (int)$m['ts'])) ?><?= $m['mailed'] ? '' : ' &middot; <em>not mailed</em>' ?>
  </header>
  <p><?= nl2br(e($m['message'])) ?></p>
  <form class="inline" method="post" action="admin.php?days=<?= $days ?>">
    <input type="hidden" name="csrf" value="<?= e($token) ?>"><input type="hidden" name="id" value="<?= (int)$m['id'] ?>">
    <button class="btn small ghost" type="submit" name="do" value="<?= $m['is_read'] ? 'unread' : 'read' ?>"><?= $m['is_read'] ? 'Mark unread' : 'Mark read' ?></button>
    <button class="btn small ghost" type="submit" name="do" value="delete">Delete</button>
  </form>
</article>
<?php endforeach; ?>
<?php if (!$messages) : ?>
<p>No message yet.</p>
<?php endif; ?>
<?php admin_foot();
