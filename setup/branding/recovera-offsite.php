<?php
declare(strict_types=1);

$rawHost = (string) ($_SERVER['HTTP_HOST'] ?? '');
$host = parse_url('http://' . $rawHost, PHP_URL_HOST);
$host = is_string($host) ? trim($host, '[]') : '';
$validIp = filter_var($host, FILTER_VALIDATE_IP) !== false;
$validName = preg_match('/^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$/', $host) === 1;
if (!$validIp && !$validName) {
    $host = '127.0.0.1';
}
if (filter_var($host, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6) !== false) {
    $host = '[' . $host . ']';
}

$target = 'https://' . $host . ':9443/';
header('Cache-Control: no-store');
header('Location: ' . $target, true, 302);
?><!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Recovera Peer Replication</title></head>
<body><p><a href="<?= htmlspecialchars($target, ENT_QUOTES, 'UTF-8') ?>">Open Recovera Peer Replication</a></p></body>
