# Snapshot helpers used during the build. Run after vc-login.ps1.
#   .\vc-snapshot.ps1 -Name pre-package-install -Description '...'
#   .\vc-snapshot.ps1 -Name configured -Replace post-package-install
#   .\vc-snapshot.ps1 -Revert pre-package-install
param(
  [string]$Name,
  [string]$Description = '',
  [string]$Replace,
  [string]$Revert
)
. (Join-Path $PSScriptRoot 'vc-connect.ps1')
$vm = Get-VM spf-datto-pkgs

if ($Revert) {
  # Restores disk AND config to the snapshot; vApp properties (cloud-init) are NOT reverted
  Set-VM -VM $vm -Snapshot (Get-Snapshot -VM $vm -Name $Revert) -Confirm:$false | Out-Null
  if ((Get-VM $vm.Name).PowerState -ne 'PoweredOn') { Start-VM -VM $vm | Out-Null }
  "reverted to $Revert"
}
if ($Replace) {
  Get-Snapshot -VM $vm -Name $Replace | Remove-Snapshot -Confirm:$false
  "removed $Replace"
}
if ($Name) {
  $s = New-Snapshot -VM $vm -Name $Name -Description $Description -Confirm:$false
  "created $($s.Name) at $($s.Created)"
}
Get-Snapshot -VM $vm | Select-Object Name, Created, @{n='SizeGB';e={[math]::Round($_.SizeGB,2)}} | Format-Table -AutoSize
