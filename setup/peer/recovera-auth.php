<?php
declare(strict_types=1);

use Datto\User\WebUserService;

if (PHP_SAPI !== 'cli' || count($argv) !== 2) {
    exit(2);
}

$username = (string) $argv[1];
$password = (string) stream_get_contents(STDIN);
if (!preg_match('/^[a-z_][a-z0-9_-]{0,31}$/i', $username) || strlen($password) > 4096) {
    exit(1);
}

try {
    require_once '/datto/scripts/status-utils.php';
    require_once '/usr/lib/datto/device/vendor/autoload.php';
    $users = new WebUserService();
    $authorized = $users->exists($username)
        && $users->isWebAccessEnabled($username)
        && $users->checkPassword($username, $password)
        && in_array('ROLE_ADMIN', $users->getRoles($username), true);
    exit($authorized ? 0 : 1);
} catch (Throwable $error) {
    error_log('Recovera local administrator authentication failed: ' . $error->getMessage());
    exit(2);
}
