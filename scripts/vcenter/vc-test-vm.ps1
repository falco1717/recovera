# Throwaway VM for testing setup/setup.sh end-to-end. Run after vc-login.ps1.
#   .\vc-test-vm.ps1 -Action deploy -Ova <path to jammy-server-cloudimg-amd64.ova>
#   .\vc-test-vm.ps1 -Action delete
param(
  [ValidateSet('deploy','delete')][string]$Action = 'deploy',
  [string]$Name = 'spf-datto-test',
  [string]$Ova = (Join-Path $PSScriptRoot 'ova\jammy-server-cloudimg-amd64.ova'),
  [int]$ZfsDiskGB = 50
)
. (Join-Path $PSScriptRoot 'vc-connect.ps1')

if ($Action -eq 'delete') {
  $vm = Get-VM -Name $Name -ErrorAction SilentlyContinue
  if (-not $vm) { "no VM named $Name"; return }
  if ($vm.Name -notlike '*-test') { throw "refusing to delete $($vm.Name): not a *-test VM" }
  if ($vm.PowerState -eq 'PoweredOn') { Stop-VM -VM $vm -Kill -Confirm:$false | Out-Null }
  Remove-VM -VM $vm -DeletePermanently -Confirm:$false
  "deleted $Name"
  return
}

if (Get-VM -Name $Name -ErrorAction SilentlyContinue) { throw "$Name already exists" }
$PubKey = (Get-Content -Raw 'F:\Users\jfarmer\Documents\keys\sshkey Public.pub').Trim()
$userData = @"
#cloud-config
hostname: $Name
manage_etc_hosts: true
package_update: false
package_upgrade: false
ssh_pwauth: false
users:
  - default
"@
$ovf = Get-OvfConfiguration -Ovf $Ova
$ovf.Common.hostname.Value    = $Name
$ovf.Common.instance_id.Value = "$Name-1"
$ovf.Common.public_keys.Value = $PubKey
$ovf.Common.user_data.Value   = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))
$netKey = @($ovf.NetworkMapping | Get-Member -MemberType CodeProperty, NoteProperty | Select-Object -ExpandProperty Name)[0]
$ovf.NetworkMapping.$netKey.Value = Get-VDPortgroup 'Servers-VLAN3'
$vm = Import-VApp -Source $Ova -OvfConfiguration $ovf -Name $Name -VMHost (Get-VMHost '10.0.3.11') -Datastore (Get-Datastore 'Datastore2') -DiskStorageFormat Thin
$vm = Set-VM -VM $vm -NumCpu 2 -MemoryGB 4 -Confirm:$false
Get-HardDisk -VM $vm | Select-Object -First 1 | Set-HardDisk -CapacityGB 40 -Confirm:$false | Out-Null
New-HardDisk -VM $vm -CapacityGB $ZfsDiskGB -Datastore (Get-Datastore 'Farmer-NAS-VMFS') -StorageFormat Thin -Confirm:$false | Out-Null
$vm = Start-VM -VM $vm
$ip = $null
for ($i = 0; $i -lt 60 -and -not $ip; $i++) {
  Start-Sleep 5
  $ip = (Get-VM $Name).Guest.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notmatch '^169\.254' } | Select-Object -First 1
}
$vm = Get-VM $Name
"VM: $Name  power: $($vm.PowerState)  disks: $((Get-HardDisk -VM $vm | ForEach-Object { "$($_.CapacityGB)GB" }) -join ' + ')  mac: $((Get-NetworkAdapter -VM $vm).MacAddress)"
"IP: $ip"
