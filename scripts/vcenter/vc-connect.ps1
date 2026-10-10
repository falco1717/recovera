# Reuse the session the user opened in vc-login.ps1 (no credentials here).
$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'
Import-Module VMware.VimAutomation.Core -WarningAction SilentlyContinue
Set-PowerCLIConfiguration -Scope Session -InvalidCertificateAction Ignore -ParticipateInCEIP $false -Confirm:$false | Out-Null
$secret = Get-Content -Raw (Join-Path $PSScriptRoot 'vc-session.txt')
$null = Connect-VIServer -Server 10.0.3.12 -Session $secret.Trim()
