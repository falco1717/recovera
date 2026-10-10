. (Join-Path $PSScriptRoot 'vc-connect.ps1')

$Name    = 'spf-datto-pkgs'
$Ova     = Join-Path $PSScriptRoot 'ova\jammy-server-cloudimg-amd64.ova'
$PubKey  = (Get-Content -Raw 'F:\Users\jfarmer\Documents\keys\sshkey Public.pub').Trim()
$VMHost  = Get-VMHost '10.0.3.11'
$DS      = Get-Datastore 'Datastore2'
$PG      = Get-VDPortgroup 'Servers-VLAN3'

if (Get-VM -Name $Name -ErrorAction SilentlyContinue) { throw "A VM named $Name already exists; not touching it." }

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
$ovf.NetworkMapping.$netKey.Value = $PG

"Importing OVA (network mapping '$netKey' -> $($PG.Name))..."
$vm = Import-VApp -Source $Ova -OvfConfiguration $ovf -Name $Name -VMHost $VMHost -Datastore $DS -DiskStorageFormat Thin

# Size before first boot so cloud-init grows the root filesystem to the full disk
$vm = Set-VM -VM $vm -NumCpu 2 -MemoryGB 4 -Confirm:$false
Get-HardDisk -VM $vm | Select-Object -First 1 | Set-HardDisk -CapacityGB 40 -Confirm:$false | Out-Null

"Powering on..."
$vm = Start-VM -VM $vm
$ip = $null
for ($i = 0; $i -lt 60 -and -not $ip; $i++) {
  Start-Sleep 5
  $ip = (Get-VM $Name).Guest.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notmatch '^169\.254' } | Select-Object -First 1
}
$vm = Get-VM $Name
"VM: $($vm.Name)  power: $($vm.PowerState)  cpu: $($vm.NumCpu)  mem: $($vm.MemoryGB)GB  disk: $((Get-HardDisk -VM $vm | Measure-Object CapacityGB -Sum).Sum)GB  tools: $($vm.ExtensionData.Guest.ToolsRunningStatus)"
"IP: $ip"
