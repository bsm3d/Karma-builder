<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : what the contact form accepts and what is done with a message: checks, storage, mail
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
    $subject = '=?UTF-8?B?' . base64_encode('[Karma Builder] ' . TOPICS[$m['topic']] . ' from ' . $m['name']) . '?=';
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
// The answer of the form as [http status, data]. The checks come in this order: the limit first, so that an abusive client cannot make
// the server parse its body again and again, then where the request comes from, then the token.
function handle_contact(): array
{
    if (!rate_ok('contact:' . visitor_hash(false), 5, 3600)) {
        return [429, ['ok' => false, 'errors' => ['Too many messages from your connection, please try again in an hour.']]];
    }
    // all connections together: a wave of robots that use many addresses cannot flood the mailbox
    if (!rate_ok('contact:everyone', 60, 3600)) {
        return [429, ['ok' => false, 'errors' => ['The form is very busy right now, please try again later.']]];
    }
    if (body_too_big()) {
        return [413, ['ok' => false, 'errors' => ['The message is too big.']]];
    }
    if (!same_site_request()) {
        return [403, ['ok' => false, 'errors' => ['The message cannot be sent from here.']]];
    }
    $token = is_string($_POST['token'] ?? null) ? $_POST['token'] : '';
    $state = form_token_check($token);
    if (in_array($state, ['bad', 'expired', 'used'], true)) {
        return [400, ['ok' => false, 'errors' => ['The form expired. Please reload the page and send it again.']]];
    }
    // a robot fills every field and is quick: it is told that it worked, and nothing is kept
    if ($state === 'early' || !empty($_POST['_gotcha'])) {
        return [200, ['ok' => true]];
    }
    $name = clean_line(is_string($_POST['name'] ?? null) ? $_POST['name'] : '', NAME_MAX);
    $email = clean_line(is_string($_POST['email'] ?? null) ? $_POST['email'] : '', MAIL_MAX);
    $topic = is_string($_POST['topic'] ?? null) ? $_POST['topic'] : '';
    $message = clean_body(is_string($_POST['message'] ?? null) ? $_POST['message'] : '');
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
        return [422, ['ok' => false, 'errors' => $errors]];
    }
    if (!form_token_use($token)) {
        return [400, ['ok' => false, 'errors' => ['The form expired. Please reload the page and send it again.']]];
    }
    // the same text again, from anywhere, within a day: a robot that repeats itself. It is told that it worked.
    if (!rate_ok('same:' . hash('sha256', mb_strtolower($message, 'UTF-8')), 1, 86400)) {
        return [200, ['ok' => true]];
    }
    $insert = db()->prepare('INSERT INTO messages (ts, name, email, topic, message) VALUES (?, ?, ?, ?, ?)');
    $insert->execute([time(), $name, $email, $topic, $message]);
    $id = (int)db()->lastInsertId();
    if (send_message_mail(['name' => $name, 'email' => $email, 'topic' => $topic, 'message' => $message])) {
        db()->prepare('UPDATE messages SET mailed = 1 WHERE id = ?')->execute([$id]);
    }
    return [200, ['ok' => true]];
}
