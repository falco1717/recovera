# Interactive vCenter sign-in. The password is typed here by the user and never stored;
# only the resulting session secret is saved so another PowerCLI process can reuse the session.
$ErrorActionPreference = 'Stop'
Import-Module VMware.VimAutomation.Core -WarningAction SilentlyContinue
Set-PowerCLIConfiguration -Scope Session -InvalidCertificateAction Ignore -ParticipateInCEIP $false -Confirm:$false | Out-Null

$out = Join-Path $PSScriptRoot 'vc-session.txt'
$cred = Get-Credential -UserName 'administrator@vsphere.local' -Message 'vCenter 10.0.3.12'
$vi = Connect-VIServer -Server 10.0.3.12 -Credential $cred
$secret = if ($vi.SessionSecret) { $vi.SessionSecret } else { $vi.SessionId }
Set-Content -Path $out -Value $secret -NoNewline
Write-Host ""
Write-Host "Connected to $($vi.Name) (vCenter $($vi.Version)) as $($vi.User)." -ForegroundColor Green
Write-Host "Session saved for Claude. You can leave this tab open or close it; the session stays valid."
