<?php
declare(strict_types=1);

use Datto\User\WebUserService;

require_once '/datto/scripts/status-utils.php';
require_once '/usr/lib/datto/device/vendor/autoload.php';

function requestStatus(string $username, string $password): string
{
    $process = proc_open([
        '/usr/bin/curl', '-sk', '-o', '/dev/null', '-w', '%{http_code}',
        '-u', $username . ':' . $password, 'https://127.0.0.1:9443/v1/admin/status',
    ], [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes);
    if (!is_resource($process)) {
        throw new RuntimeException('Could not launch curl');
    }
    fclose($pipes[0]);
    $status = stream_get_contents($pipes[1]);
    $error = stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    $exit = proc_close($process);
    if ($exit !== 0) {
        throw new RuntimeException('curl failed: ' . trim((string) $error));
    }
    return trim((string) $status);
}

$username = 'recovera_test_' . bin2hex(random_bytes(5));
$password = bin2hex(random_bytes(18));
$users = new WebUserService();

try {
    $users->create($username, $password);
    $users->setRoles($username, ['ROLE_ADMIN', 'ROLE_BASIC_ACCESS']);
    if (requestStatus($username, $password) !== '200') {
        throw new RuntimeException('Registered administrator was not accepted');
    }
    if (requestStatus($username, $password . '-wrong') !== '401') {
        throw new RuntimeException('Incorrect password was not rejected');
    }
    $users->setRoles($username, ['ROLE_BASIC_ACCESS']);
    if (requestStatus($username, $password) !== '401') {
        throw new RuntimeException('Non-administrator was not rejected');
    }
    echo "Recovera authentication integration test passed\n";
} finally {
    if ($users->exists($username)) {
        $users->delete($username);
    }
}
