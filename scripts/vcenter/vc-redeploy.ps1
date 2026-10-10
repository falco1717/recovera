. (Join-Path $PSScriptRoot 'vc-connect.ps1')

$Name    = 'spf-datto-pkgs'
$OldMac  = '00:50:56:9a:22:86'
$IP      = '10.0.3.200'
$Ova     = Join-Path $PSScriptRoot 'ova\jammy-server-cloudimg-amd64.ova'
$PubKey  = (Get-Content -Raw 'F:\Users\jfarmer\Documents\keys\sshkey Public.pub').Trim()
$VMHost  = Get-VMHost '10.0.3.11'
$DS      = Get-Datastore 'Datastore2'
$PG      = Get-VDPortgroup 'Servers-VLAN3'

# 1. Remove the first attempt, only if it is exactly the VM created earlier
$old = Get-VM -Name $Name -ErrorAction SilentlyContinue
if ($old) {
  $mac = (Get-NetworkAdapter -VM $old).MacAddress
  if ($mac -ne $OldMac) { throw "$Name has MAC $mac, not $OldMac. Not deleting." }
  if ($old.PowerState -eq 'PoweredOn') { Stop-VM -VM $old -Kill -Confirm:$false | Out-Null }
  Remove-VM -VM $old -DeletePermanently -Confirm:$false
  "Deleted previous $Name ($mac)"
}

# 2. Import with cloud-init user-data
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
$ovf.Common.instance_id.Value = "$Name-2"
$ovf.Common.public_keys.Value = $PubKey
$ovf.Common.user_data.Value   = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))
$netKey = @($ovf.NetworkMapping | Get-Member -MemberType CodeProperty, NoteProperty | Select-Object -ExpandProperty Name)[0]
$ovf.NetworkMapping.$netKey.Value = $PG
$vm = Import-VApp -Source $Ova -OvfConfiguration $ovf -Name $Name -VMHost $VMHost -Datastore $DS -DiskStorageFormat Thin
"Imported $Name"

# 3. Static network config: cloud-init's OVF datasource reads a base64 'network-config' property
$netCfg = @"
version: 2
ethernets:
  lan:
    match:
      name: "en*"
    dhcp4: false
    dhcp6: false
    addresses: [$IP/24]
    routes:
      - to: default
        via: 10.0.3.1
    nameservers:
      addresses: [10.0.3.1]
"@
$props = $vm.ExtensionData.Config.VAppConfig.Property
$spec = New-Object VMware.Vim.VirtualMachineConfigSpec
$spec.VAppConfig = New-Object VMware.Vim.VmConfigSpec
$p = New-Object VMware.Vim.VAppPropertySpec
$p.Operation = 'add'
$p.Info = New-Object VMware.Vim.VAppPropertyInfo
$p.Info.Key = ([int]($props | Measure-Object Key -Maximum).Maximum) + 1
$p.Info.Id = 'network-config'
$p.Info.Label = 'Network config (base64 netplan v2)'
$p.Info.Type = 'string'
$p.Info.UserConfigurable = $true
$p.Info.Value = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($netCfg))
$spec.VAppConfig.Property = @($p)
$vm.ExtensionData.ReconfigVM($spec)
"Added network-config property ($IP/24 via 10.0.3.1)"

# 4. Size before first boot so cloud-init grows the root filesystem
$vm = Set-VM -VM $vm -NumCpu 2 -MemoryGB 4 -Confirm:$false
Get-HardDisk -VM $vm | Select-Object -First 1 | Set-HardDisk -CapacityGB 40 -Confirm:$false | Out-Null

$vm = Start-VM -VM $vm
$ips = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep 5
  $ips = (Get-VM $Name).Guest.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' }
  if ($ips) { break }
}
$vm = Get-VM $Name
"VM: $($vm.Name)  power: $($vm.PowerState)  cpu: $($vm.NumCpu)  mem: $($vm.MemoryGB)GB  disk: $((Get-HardDisk -VM $vm | Measure-Object CapacityGB -Sum).Sum)GB  mac: $((Get-NetworkAdapter -VM $vm).MacAddress)"
"IPv4: $($ips -join ', ')"
