<?php
declare(strict_types=1);

use Datto\User\WebUserService;

require_once '/datto/scripts/status-utils.php';
require_once '/usr/lib/datto/device/vendor/autoload.php';

function curlRequest(array $arguments): string
{
    $process = proc_open(array_merge(['/usr/bin/curl', '-sk'], $arguments),
        [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes);
    if (!is_resource($process)) {
        throw new RuntimeException('Could not launch curl');
    }
    fclose($pipes[0]);
    $output = stream_get_contents($pipes[1]);
    $error = stream_get_contents($pipes[2]);
    fclose($pipes[1]); fclose($pipes[2]);
    if (proc_close($process) !== 0) {
        throw new RuntimeException('curl failed: ' . trim((string) $error));
    }
    return (string) $output;
}

$username = 'recovera_page_test_' . bin2hex(random_bytes(4));
$password = bin2hex(random_bytes(18));
$cookie = tempnam('/tmp', 'recovera-cookie-');
$users = new WebUserService();
$scheduleId = null;

try {
    $users->create($username, $password);
    $users->setRoles($username, ['ROLE_ADMIN', 'ROLE_BASIC_ACCESS']);
    $login = curlRequest(['-c', $cookie, 'https://127.0.0.1/login']);
    if (!preg_match('/name="csrf" value="([^"]+)"/', $login, $match)) {
        throw new RuntimeException('Login CSRF token was not found');
    }
    $status = curlRequest(['-b', $cookie, '-c', $cookie, '-o', '/dev/null', '-w', '%{http_code}',
        '--data-urlencode', 'csrf=' . html_entity_decode($match[1]),
        '--data-urlencode', 'username=' . $username,
        '--data-urlencode', 'password=' . $password,
        'https://127.0.0.1/login']);
    if ($status !== '302') {
        throw new RuntimeException('Web login failed with HTTP ' . $status);
    }
    $offsite = curlRequest(['-b', $cookie, '-w', '\n%{http_code}', 'https://127.0.0.1/configure/offsite']);
    if (!str_ends_with($offsite, "\n200") || !str_contains($offsite, 'id="maxSpeed"')) {
        throw new RuntimeException('Off-site Synchronization page did not render successfully');
    }
    $target = curlRequest(['-b', $cookie, '-w', '\n%{http_code}', 'https://127.0.0.1/configure/offsite-target']);
    if (!str_ends_with($target, "\n200") || !str_contains($target, 'id="recovera-target"')) {
        throw new RuntimeException('Off-site Target page did not render successfully');
    }
    if (!preg_match('/id="recovera-csrf".*?name="csrf" value="([^"]+)"/s', $target, $csrfMatch)) {
        throw new RuntimeException('Off-site Target CSRF token was not found');
    }
    $pageCsrf = html_entity_decode($csrfMatch[1]);
    $statusApi = curlRequest(['-b', $cookie, '-H', 'X-Requested-With: XMLHttpRequest',
        '-w', '\n%{http_code}', 'https://127.0.0.1/api/recovera/offsite-target/status']);
    if (!str_ends_with($statusApi, "\n200") || !str_contains($statusApi, '"service":"recovera-peer"')) {
        throw new RuntimeException('Off-site Target API did not return Recovera status');
    }
    $queueApi = curlRequest(['-b', $cookie, '-H', 'X-Requested-With: XMLHttpRequest',
        '-w', '\n%{http_code}', 'https://127.0.0.1/api/recovera/offsite-target/queue-status']);
    if (!str_ends_with($queueApi, "\n200") || !str_contains($queueApi, '"items"')) {
        throw new RuntimeException('Recovery-point queue status API did not render successfully');
    }
    $recoveryTemplate = (string) @file_get_contents(
        '/usr/lib/datto/device/templates/commonlookandfeel/Assets/RecoveryPoints/index.html.twig');
    $recoveryScript = (string) @file_get_contents(
        '/datto/web/commonlookandfeel/js/App/Assets/RecoveraRecoveryPoints.js');
    if (!str_contains($recoveryTemplate, 'RecoveraRecoveryPoints.js') ||
        !str_contains($recoveryScript, 'v1/device/snapshot/send')) {
        throw new RuntimeException('Native recovery-point queue bridge is not installed');
    }
    $protectTemplate = (string) @file_get_contents(
        '/usr/lib/datto/device/templates/commonlookandfeel/Agents/Add/index.html.twig');
    $replicationTemplate = (string) @file_get_contents(
        '/usr/lib/datto/device/templates/commonlookandfeel/Assets/Configure/cloud.backup.html.twig');
    $protectScript = (string) @file_get_contents(
        '/datto/web/commonlookandfeel/js/App/Agents/RecoveraProtectSystem.js');
    if (!str_contains($protectTemplate, 'RecoveraProtectSystem.js') ||
        !str_contains($protectTemplate, 'recovera-protect-csrf') ||
        !str_contains($replicationTemplate, "inWizard or feature.isSupported('FEATURE_PEER_REPLICATION')") ||
        !str_contains($protectScript, "request('wizard-rule'")) {
        throw new RuntimeException('Protect a System replication integration is not installed');
    }
    $added = curlRequest(['-b', $cookie, '-H', 'X-Requested-With: XMLHttpRequest',
        '--data-urlencode', 'csrf=' . $pageCsrf, '--data-urlencode',
        'payload={"secondsWeekStart":12345,"secondsWeekEnd":12600,"speed":1024}',
        'https://127.0.0.1/api/recovera/offsite-target/schedule-add']);
    try {
        $addedValue = json_decode($added, true, flags: JSON_THROW_ON_ERROR);
    } catch (JsonException $error) {
        throw new RuntimeException('Schedule add returned invalid JSON: ' . substr($added, 0, 500), 0, $error);
    }
    $scheduleId = (int) ($addedValue['schedID'] ?? 0);
    if ($scheduleId < 1) {
        throw new RuntimeException('Schedule add did not return an ID');
    }
    $deleted = curlRequest(['-b', $cookie, '-H', 'X-Requested-With: XMLHttpRequest',
        '--data-urlencode', 'csrf=' . $pageCsrf, '--data-urlencode',
        'payload=' . json_encode(['scheduleId' => $scheduleId]),
        'https://127.0.0.1/api/recovera/offsite-target/schedule-delete']);
    if (!str_contains($deleted, '"ok":true')) {
        throw new RuntimeException('Schedule delete failed');
    }
    $scheduleId = null;
    echo "Recovera native off-site pages integration test passed\n";
} finally {
    if ($scheduleId !== null) {
        @curlRequest(['-b', $cookie, '-H', 'X-Requested-With: XMLHttpRequest',
            '--data-urlencode', 'csrf=' . ($pageCsrf ?? ''), '--data-urlencode',
            'payload=' . json_encode(['scheduleId' => $scheduleId]),
            'https://127.0.0.1/api/recovera/offsite-target/schedule-delete']);
    }
    @unlink($cookie);
    if ($users->exists($username)) {
        $users->delete($username);
    }
}
