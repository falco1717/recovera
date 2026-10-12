<?php

namespace Datto\App\Controller\Web\Configure;

use Datto\App\Security\RequiresFeature;
use Datto\App\Security\RequiresPermission;
use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;

final class RecoveraTargetController extends AbstractController
{
    /**
     * @RequiresFeature("FEATURE_USER_INTERFACE")
     * @RequiresPermission("PERMISSION_OFFSITE_WRITE")
     */
    public function indexAction(): Response
    {
        return $this->render('commonlookandfeel/Configure/RecoveraTarget/index.html.twig');
    }

    /**
     * @RequiresFeature("FEATURE_USER_INTERFACE")
     * @RequiresPermission("PERMISSION_OFFSITE_WRITE")
     */
    public function apiAction(Request $request, string $operation): JsonResponse
    {
        if ($request->headers->get('X-Requested-With') !== 'XMLHttpRequest') {
            return new JsonResponse(['error' => 'Invalid request'], 400);
        }
        $map = [
            'status' => ['GET', '/v1/admin/status'],
            'pairing-code' => ['POST', '/v1/admin/pairing-code'],
            'discover' => ['POST', '/v1/admin/discover'],
            'peer' => ['POST', '/v1/admin/peer'],
            'rule' => ['POST', '/v1/admin/rule'],
            'sync' => ['POST', '/v1/admin/sync'],
            'offsite' => ['GET', '/v1/admin/offsite'],
            'schedule-add' => ['POST', '/v1/admin/offsite/schedule-add'],
            'schedule-delete' => ['POST', '/v1/admin/offsite/schedule-delete'],
            'speed-set' => ['POST', '/v1/admin/offsite/speed-set'],
            'speed-test' => ['POST', '/v1/admin/offsite/speed-test'],
            'concurrency-set' => ['POST', '/v1/admin/offsite/concurrency-set'],
        ];
        if (!isset($map[$operation])) {
            return new JsonResponse(['error' => 'Unknown operation'], 404);
        }
        [$method, $path] = $map[$operation];
        if ($request->getMethod() !== $method) {
            return new JsonResponse(['error' => 'Method not allowed'], 405);
        }
        $token = @trim((string) file_get_contents('/etc/recovera-peer/web.token'));
        if ($token === '') {
            return new JsonResponse(['error' => 'Recovera peer service is not initialized'], 503);
        }
        $port = 9443;
        $config = @json_decode((string) file_get_contents('/etc/recovera-peer/config.json'), true);
        if (is_array($config) && isset($config['port'])) {
            $port = (int) $config['port'];
        }
        $curl = curl_init('https://127.0.0.1:' . $port . $path);
        curl_setopt_array($curl, [
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_TIMEOUT => $operation === 'sync' ? 3600 : 30,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-Recovera-Internal: ' . $token],
        ]);
        if ($method === 'POST') {
            $payload = (string) ($request->request->get('payload') ?: $request->getContent() ?: '{}');
            curl_setopt($curl, CURLOPT_POSTFIELDS, $payload);
        }
        $body = curl_exec($curl);
        $status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
        $error = curl_error($curl);
        curl_close($curl);
        if ($body === false) {
            return new JsonResponse(['error' => 'Recovera peer service is unavailable: ' . $error], 503);
        }
        return new JsonResponse(json_decode($body, true) ?: ['error' => 'Invalid peer response'], $status ?: 502);
    }
}
