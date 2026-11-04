<#
install-recovera-agent.ps1 - enroll a Windows host's Datto Windows Agent with an
offline Recovera appliance.

STATUS: UNTESTED. Unlike the Linux agent, the Datto Windows Agent (ShadowSnap /
DWA) is a closed, compiled MSI that cannot be rebuilt, and its device trust is
pushed by the appliance during pairing (SIRIS `snapctl agent:cert:inject`, the
"Inject new root CA certificate" shadowsnap command) rather than by swapping a
file as on Linux. This script only installs the stock agent and stages Recovera's
root CA; the trust injection is driven from the Recovera side. It was written
from the SIRIS source layout, not validated against a live Windows agent.

Run elevated (Administrator).

  .\install-recovera-agent.ps1 -StockInstaller <path-to-DattoWindowsAgent.msi> -RecoveraCaCert <path-to-ca.crt>
#>
param(
  [Parameter(Mandatory = $true)][string]$StockInstaller,
  [Parameter(Mandatory = $true)][string]$RecoveraCaCert
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $StockInstaller)) { throw "installer not found: $StockInstaller" }
if (-not (Test-Path $RecoveraCaCert)) { throw "CA cert not found: $RecoveraCaCert" }

Write-Host 'Installing the stock Datto Windows Agent...'
Start-Process msiexec.exe -ArgumentList "/i `"$StockInstaller`" /qn" -Wait

# Stage Recovera's CA into the agent's SSL dir so a device-side inject/pair can
# adopt it. Path matches the shadowsnap layout seen in the SIRIS command whitelist.
$sslDir = Join-Path ${env:ProgramFiles(x86)} 'StorageCraft\ShadowProtect\ShadowSnap\ssl'
if (-not (Test-Path $sslDir)) { New-Item -ItemType Directory -Path $sslDir -Force | Out-Null }
Copy-Item $RecoveraCaCert (Join-Path $sslDir 'ca.crt') -Force
Write-Host "Staged Recovera CA at $sslDir\ca.crt"

Write-Host 'Next (on the Recovera appliance):'
Write-Host '  sudo snapctl agent:cert:inject   # push the offline root CA to this agent'
Write-Host '  sudo snapctl agent:add <thisWindowsIP> --offsiteTarget noOffsite'
Write-Host 'NOTE: this path is untested end-to-end; see docs/offline-agent-pairing.md.'
