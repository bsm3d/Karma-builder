<?php
// Karma Builder website
// Benoît Saint-Moulin | www.bsm3d.com
// Function : the SQLite database (stats, messages, rate limits) opened with PDO, tables created on first use
// PHP : 8.1 and later (pdo_sqlite)
// Version : 1.0.0

declare(strict_types=1);

// ------------------------------------------------------------
function db(): PDO
{
    static $pdo = null;
    if ($pdo !== null) {
        return $pdo;
    }
    // `data_dir` can be a folder outside the web root. Inside it, the file has a name nobody can guess, in case a deny rule fails.
    $folder = rtrim((string)cfg('data_dir', __DIR__ . '/../data'), '/\\');
    if (!is_dir($folder) && !mkdir($folder, 0750, true) && !is_dir($folder)) {
        throw new RuntimeException('The data folder cannot be created.');
    }
    $file = 'site-' . substr(hash_hmac('sha256', 'database', (string)cfg('salt')), 0, 16) . '.sqlite';
    $pdo = new PDO('sqlite:' . $folder . '/' . $file, null, null, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ]);
    $pdo->exec('PRAGMA busy_timeout = 4000');
    $pdo->exec('PRAGMA journal_mode = WAL');
    $pdo->exec('CREATE TABLE IF NOT EXISTS hits (id INTEGER PRIMARY KEY, day TEXT NOT NULL, ts INTEGER NOT NULL, page TEXT NOT NULL,
                visitor TEXT NOT NULL, ref TEXT NOT NULL DEFAULT "", device TEXT NOT NULL DEFAULT "")');
    $pdo->exec('CREATE INDEX IF NOT EXISTS hits_day ON hits (day)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS downloads (id INTEGER PRIMARY KEY, day TEXT NOT NULL, ts INTEGER NOT NULL, target TEXT NOT NULL,
                visitor TEXT NOT NULL)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS downloads_day ON downloads (day)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
                topic TEXT NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, mailed INTEGER NOT NULL DEFAULT 0)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS limits (bucket TEXT NOT NULL, ts INTEGER NOT NULL)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS limits_bucket ON limits (bucket, ts)');
    return $pdo;
}

// ------------------------------------------------------------
// true when the action is allowed (and counted), false when `$max` were already made in the last `$window` seconds
function rate_ok(string $bucket, int $max, int $window): bool
{
    $pdo = db();
    $now = time();
    // count and insert in one transaction that takes the write lock first: two requests that arrive together cannot both pass
    $pdo->exec('BEGIN IMMEDIATE');
    try {
        $count = $pdo->prepare('SELECT COUNT(*) FROM limits WHERE bucket = ? AND ts > ?');
        $count->execute([$bucket, $now - $window]);
        $allowed = (int)$count->fetchColumn() < $max;
        if ($allowed) {
            $pdo->prepare('INSERT INTO limits (bucket, ts) VALUES (?, ?)')->execute([$bucket, $now]);
        }
        if (random_int(1, 50) === 1) {
            $pdo->prepare('DELETE FROM limits WHERE ts < ?')->execute([$now - 86400]);
        }
        $pdo->exec('COMMIT');
    } catch (Throwable $error) {
        $pdo->exec('ROLLBACK');
        throw $error;
    }
    return $allowed;
}

// ------------------------------------------------------------
function rate_count(string $bucket, int $window): int
{
    $count = db()->prepare('SELECT COUNT(*) FROM limits WHERE bucket = ? AND ts > ?');
    $count->execute([$bucket, time() - $window]);
    return (int)$count->fetchColumn();
}

// ------------------------------------------------------------
function rate_reset(string $bucket): void
{
    db()->prepare('DELETE FROM limits WHERE bucket = ?')->execute([$bucket]);
}
