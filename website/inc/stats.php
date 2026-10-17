<?php
// BSM Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : private page statistics: what is counted, what is not, and the figures the admin page shows
// PHP : 8.1 and later
// Version : 1.0.0

declare(strict_types=1);

const STAT_PAGES = ['home', 'guide', 'faq', 'contact'];
const DOWNLOAD_TARGETS = ['github', 'zip'];

// ------------------------------------------------------------
function is_bot(string $agent): bool
{
    if ($agent === '') {
        return true;
    }
    return (bool)preg_match('~bot|crawl|spider|slurp|curl|wget|python|java/|httpclient|headless|lighthouse|preview|fetch|monitor|scan|facebookexternalhit~i', $agent);
}

// ------------------------------------------------------------
function device_of(string $agent): string
{
    if (preg_match('~mobi|android|iphone|ipad~i', $agent)) {
        return 'mobile';
    }
    return 'desktop';
}

// ------------------------------------------------------------
// Only the host of the referrer, and nothing when it is this very site.
function referrer_host(string $referrer, string $own_host): string
{
    $host = strtolower((string)parse_url($referrer, PHP_URL_HOST));
    $host = preg_replace('~^www\.~', '', $host) ?? '';
    $own = preg_replace('~^www\.~', '', strtolower($own_host)) ?? '';
    if ($host === '' || $host === $own || strlen($host) > 80 || !preg_match('~^[a-z0-9.\-]+$~', $host)) {
        return '';
    }
    return $host;
}

// ------------------------------------------------------------
// No cookie, no address: a visitor is a hash of the day. Nothing is kept for a visitor who asks not to be followed, for a robot,
// or for a page that is not one of ours (a counter must not be a way to fill the disk).
function record_hit(string $page, string $referrer): bool
{
    $agent = $_SERVER['HTTP_USER_AGENT'] ?? '';
    if (!in_array($page, STAT_PAGES, true) || wants_privacy() || is_bot($agent)) {
        return false;
    }
    db()->prepare('INSERT INTO hits (day, ts, page, visitor, ref, device) VALUES (?, ?, ?, ?, ?, ?)')->execute([
        date('Y-m-d'), time(), $page, visitor_hash(), referrer_host($referrer, $_SERVER['HTTP_HOST'] ?? ''), device_of($agent),
    ]);
    // the figures older than about a year are of no use: they go from time to time
    if (random_int(1, 200) === 1) {
        db()->prepare('DELETE FROM hits WHERE day < ?')->execute([date('Y-m-d', strtotime('-400 days'))]);
        db()->prepare('DELETE FROM downloads WHERE day < ?')->execute([date('Y-m-d', strtotime('-400 days'))]);
    }
    return true;
}

// ------------------------------------------------------------
function record_download(string $target): bool
{
    $agent = $_SERVER['HTTP_USER_AGENT'] ?? '';
    if (!in_array($target, DOWNLOAD_TARGETS, true) || wants_privacy() || is_bot($agent)) {
        return false;
    }
    db()->prepare('INSERT INTO downloads (day, ts, target, visitor) VALUES (?, ?, ?, ?)')->execute([date('Y-m-d'), time(), $target, visitor_hash()]);
    return true;
}

// ------------------------------------------------------------
// Figures of the last `$days` days for the admin page.
function stats_report(int $days): array
{
    $pdo = db();
    $since = date('Y-m-d', strtotime('-' . ($days - 1) . ' days'));
    $rows = static function (string $sql, array $args = []) use ($pdo): array {
        $statement = $pdo->prepare($sql);
        $statement->execute($args);
        return $statement->fetchAll();
    };
    $per_day = $rows('SELECT day, COUNT(*) AS views, COUNT(DISTINCT visitor) AS visitors FROM hits WHERE day >= ? GROUP BY day ORDER BY day', [$since]);
    $total = $rows('SELECT COUNT(*) AS views, COUNT(DISTINCT visitor || day) AS visits FROM hits WHERE day >= ?', [$since])[0];
    return [
        'since'     => $since,
        'per_day'   => $per_day,
        'total'     => $total,
        'pages'     => $rows('SELECT page, COUNT(*) AS views FROM hits WHERE day >= ? GROUP BY page ORDER BY views DESC', [$since]),
        'referrers' => $rows('SELECT ref, COUNT(*) AS views FROM hits WHERE day >= ? AND ref <> "" GROUP BY ref ORDER BY views DESC LIMIT 12', [$since]),
        'devices'   => $rows('SELECT device, COUNT(*) AS views FROM hits WHERE day >= ? GROUP BY device ORDER BY views DESC', [$since]),
        'downloads' => $rows('SELECT target, COUNT(*) AS clicks FROM downloads WHERE day >= ? GROUP BY target ORDER BY clicks DESC', [$since]),
    ];
}
