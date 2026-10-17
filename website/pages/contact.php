<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : contact page and its form: checks, rate limit, honeypot, storage, mail
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

const TOPICS = ['question' => 'A question', 'bug' => 'A bug report', 'license' => 'A commercial license', 'other' => 'Something else'];
const NAME_MAX = 80;
const MAIL_MAX = 190;
const BODY_MIN = 10;
const BODY_MAX = 5000;

// ------------------------------------------------------------
// A header or a command line cannot be built from a value that holds a line break: they are taken out here, where the value comes in.
function clean_line(string $text, int $max): string
{
    $text = preg_replace('~[\x00-\x1F\x7F]+~u', ' ', $text) ?? '';
    return trim(mb_substr($text, 0, $max, 'UTF-8'));
}

// ------------------------------------------------------------
function clean_body(string $text): string
{
    $text = str_replace(["\r\n", "\r"], "\n", $text);
    $text = preg_replace('~[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]~u', '', $text) ?? '';
    return trim(mb_substr($text, 0, BODY_MAX, 'UTF-8'));
}

// ------------------------------------------------------------
function send_message_mail(array $m): bool
{
    $to = (string)cfg('contact_to', '');
    $from = (string)cfg('mail_from', '');
    if (!filter_var($to, FILTER_VALIDATE_EMAIL) || !filter_var($from, FILTER_VALIDATE_EMAIL)) {
        return false;
    }
    $subject = '[Karma Builder] ' . TOPICS[$m['topic']] . ' from ' . $m['name'];
    $subject = '=?UTF-8?B?' . base64_encode($subject) . '?=';
    $headers = [
        'From' => SITE_NAME . ' <' . $from . '>',
        'Reply-To' => $m['email'],
        'MIME-Version' => '1.0',
        'Content-Type' => 'text/plain; charset=UTF-8',
        'X-Mailer' => 'bsm-karma-site',
    ];
    $text = "Name: {$m['name']}\nEmail: {$m['email']}\nTopic: " . TOPICS[$m['topic']] . "\n\n" . $m['message'] . "\n";
    return @mail($to, $subject, $text, $headers);
}

// ------------------------------------------------------------
// The checks, in this order: the limit first, so that an abusive client cannot make the server parse its body again and again.
function handle_post(): array
{
    if (!rate_ok('contact:' . visitor_hash(false), 5, 3600)) {
        return ['status' => 'limit', 'errors' => ['Too many messages from your connection, please try again in an hour.']];
    }
    if (!csrf_ok($_POST['csrf'] ?? null)) {
        return ['status' => 'csrf', 'errors' => ['The form expired. Please send it again.']];
    }
    // a robot fills every field: it is told that it worked, and nothing is kept
    $started = (int)($_SESSION['form_ts'] ?? 0);
    if (!empty($_POST['_gotcha']) || $started === 0 || time() - $started < 3) {
        return ['status' => 'sent', 'errors' => []];
    }
    $name = clean_line((string)($_POST['name'] ?? ''), NAME_MAX);
    $email = clean_line((string)($_POST['email'] ?? ''), MAIL_MAX);
    $topic = (string)($_POST['topic'] ?? '');
    $message = clean_body((string)($_POST['message'] ?? ''));
    $errors = [];
    if ($name === '') {
        $errors[] = 'Please give your name.';
    }
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $errors[] = 'Please give an email address I can answer to.';
    }
    if (!isset(TOPICS[$topic])) {
        $errors[] = 'Please choose a topic.';
    }
    if (mb_strlen($message, 'UTF-8') < BODY_MIN) {
        $errors[] = 'Your message is a little short.';
    }
    if (preg_match_all('~https?://~i', $message) > 3) {
        $errors[] = 'Too many links in the message.';
    }
    if ($errors) {
        return ['status' => 'invalid', 'errors' => $errors, 'old' => ['name' => $name, 'email' => $email, 'topic' => $topic, 'message' => $message]];
    }
    $row = ['name' => $name, 'email' => $email, 'topic' => $topic, 'message' => $message];
    $insert = db()->prepare('INSERT INTO messages (ts, name, email, topic, message) VALUES (?, ?, ?, ?, ?)');
    $insert->execute([time(), $name, $email, $topic, $message]);
    $id = (int)db()->lastInsertId();
    if (send_message_mail($row)) {
        db()->prepare('UPDATE messages SET mailed = 1 WHERE id = ?')->execute([$id]);
    }
    unset($_SESSION['form_ts']);
    return ['status' => 'sent', 'errors' => []];
}

// ------------------------------------------------------------
session_boot();
$result = ['status' => 'form', 'errors' => []];
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $result = handle_post();
    if ($result['status'] === 'sent') {
        $_SESSION['flash_sent'] = true;
        go(page_url('contact'));
    }
    http_response_code($result['status'] === 'invalid' ? 422 : ($result['status'] === 'limit' ? 429 : 400));
}
$sent = !empty($_SESSION['flash_sent']);
unset($_SESSION['flash_sent']);
if (!$sent) {
    $_SESSION['form_ts'] = $_SESSION['form_ts'] ?? time();
}
$old = $result['old'] ?? ['name' => '', 'email' => '', 'topic' => 'question', 'message' => ''];
$prefill = isset($_GET['topic']) && is_string($_GET['topic']) && isset(TOPICS[$_GET['topic']]) ? $_GET['topic'] : null;
if ($prefill !== null && $old['topic'] === 'question') {
    $old['topic'] = $prefill;
}

page_head('contact', 'Contact', 'Write to the author of BSM Karma Builder: a question, a bug report, or a commercial license for your studio.');
?>
<div class="wrap narrow">
  <h1>Contact</h1>
<?php if ($sent) : ?>
  <div class="callout ok" role="status"><strong>Message sent.</strong> Thank you, I will answer as soon as I can.</div>
  <p><a class="btn" href="<?= e(page_url('home')) ?>">Back to the home page</a></p>
<?php else : ?>
  <p class="lead">A question, a bug, or a license for your studio. For a bug, add your Houdini version and what the Log tab says (the <a href="<?= e(page_url('faq')) ?>#debug">FAQ</a> explains where to find it).</p>
<?php if ($result['errors']) : ?>
  <div class="callout warn" role="alert"><strong>The message was not sent.</strong>
    <ul><?php foreach ($result['errors'] as $error) : ?><li><?= e($error) ?></li><?php endforeach; ?></ul>
  </div>
<?php endif; ?>
  <form class="form" method="post" action="<?= e(page_url('contact')) ?>" novalidate>
    <input type="hidden" name="csrf" value="<?= e(csrf_token()) ?>">
    <div class="hp" aria-hidden="true"><label>Leave this empty<input type="text" name="_gotcha" tabindex="-1" autocomplete="off"></label></div>
    <label for="name">Your name</label>
    <input id="name" name="name" type="text" maxlength="<?= NAME_MAX ?>" required autocomplete="name" value="<?= e($old['name']) ?>">
    <label for="email">Your email address</label>
    <input id="email" name="email" type="email" maxlength="<?= MAIL_MAX ?>" required autocomplete="email" value="<?= e($old['email']) ?>">
    <label for="topic">About</label>
    <select id="topic" name="topic">
<?php foreach (TOPICS as $key => $label) : ?>
      <option value="<?= e($key) ?>"<?= $old['topic'] === $key ? ' selected' : '' ?>><?= e($label) ?></option>
<?php endforeach; ?>
    </select>
    <label for="message">Your message</label>
    <textarea id="message" name="message" rows="9" maxlength="<?= BODY_MAX ?>" required><?= e($old['message']) ?></textarea>
    <p class="muted small">Your message is stored on this site and mailed to me, only to answer you.</p>
    <button class="btn" type="submit">Send</button>
  </form>
<?php endif; ?>
</div>
<?php page_foot();
