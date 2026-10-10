. (Join-Path $PSScriptRoot 'vc-connect.ps1')
$vm = Get-VM spf-datto-pkgs

$userData = @"
#cloud-config
hostname: spf-datto-pkgs
manage_etc_hosts: true
package_update: false
package_upgrade: false
ssh_pwauth: false
ssh_deletekeys: false
users:
  - default
bootcmd:
  - [ sh, -c, "getent group remote-users >/dev/null && usermod -aG remote-users ubuntu || true" ]
"@

if ($vm.PowerState -eq 'PoweredOn') {
  Stop-VMGuest -VM $vm -Confirm:$false | Out-Null
  for ($i = 0; $i -lt 60 -and (Get-VM $vm.Name).PowerState -ne 'PoweredOff'; $i++) { Start-Sleep 3 }
}
$vm = Get-VM $vm.Name
"power: $($vm.PowerState)"
if ($vm.PowerState -ne 'PoweredOff') { throw 'VM did not shut down cleanly; not editing properties.' }

$props = $vm.ExtensionData.Config.VAppConfig.Property
$edits = @()
foreach ($pair in @(@('instance-id', 'spf-datto-pkgs-3'),
                    @('user-data', [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))))) {
  $cur = $props | Where-Object Id -eq $pair[0]
  if (-not $cur) { throw "vApp property $($pair[0]) not found" }
  $e = New-Object VMware.Vim.VAppPropertySpec
  $e.Operation = 'edit'
  $e.Info = $cur
  $e.Info.Value = $pair[1]
  $edits += $e
}
$spec = New-Object VMware.Vim.VirtualMachineConfigSpec
$spec.VAppConfig = New-Object VMware.Vim.VmConfigSpec
$spec.VAppConfig.Property = $edits
$vm.ExtensionData.ReconfigVM($spec)
"vApp properties updated: instance-id -> spf-datto-pkgs-3, user-data adds ubuntu to remote-users"

Start-VM -VM $vm | Out-Null
"powered on"
