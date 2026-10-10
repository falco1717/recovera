. (Join-Path $PSScriptRoot 'vc-connect.ps1')

"=== Datacenters / clusters"
Get-Datacenter | ForEach-Object { "DC: $($_.Name)" }
Get-Cluster | Select-Object Name, HAEnabled, DrsEnabled, DrsAutomationLevel | Format-Table -AutoSize | Out-String -Width 200

"=== Hosts"
Get-VMHost | Select-Object Name, ConnectionState, PowerState, Version,
  @{n='CPU%';e={[math]::Round(100*$_.CpuUsageMhz/$_.CpuTotalMhz)}},
  @{n='MemFreeGB';e={[math]::Round($_.MemoryTotalGB-$_.MemoryUsageGB,1)}},
  @{n='Cluster';e={$_.Parent.Name}} | Format-Table -AutoSize | Out-String -Width 200

"=== Datastores"
Get-Datastore | Sort-Object FreeSpaceGB -Descending | Select-Object Name, Type, State,
  @{n='FreeGB';e={[math]::Round($_.FreeSpaceGB)}}, @{n='CapGB';e={[math]::Round($_.CapacityGB)}},
  @{n='Hosts';e={($_ | Get-VMHost).Count}} | Format-Table -AutoSize | Out-String -Width 200

"=== Port groups"
Get-VirtualPortGroup | Select-Object Name, VLanId, @{n='Switch';e={$_.VirtualSwitchName}} -Unique | Sort-Object Name | Format-Table -AutoSize | Out-String -Width 200
Get-VDPortgroup -ErrorAction SilentlyContinue | Select-Object Name, @{n='VLAN';e={$_.VlanConfiguration}}, VDSwitch | Format-Table -AutoSize | Out-String -Width 200

"=== Which port group are VMs on 10.0.3.x using?"
Get-VM | Where-Object { $_.Guest.IPAddress -match '^10\.0\.3\.' } | ForEach-Object {
  $vm = $_; $vm | Get-NetworkAdapter | ForEach-Object { "{0,-30} {1,-16} {2}" -f $vm.Name, ($vm.Guest.IPAddress -match '^10\.0\.3\.' | Select-Object -First 1), $_.NetworkName }
} | Select-Object -First 15

"=== Existing VMs named like ours / folders"
Get-VM | Where-Object Name -match 'ubuntu|pkg|datto' | Select-Object Name, PowerState | Format-Table -AutoSize | Out-String
Get-Folder -Type VM | Select-Object -ExpandProperty Name
"=== Content libraries"
Get-ContentLibrary -ErrorAction SilentlyContinue | Select-Object Name, Datastore
