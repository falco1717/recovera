# Hot-add the 3 TB thin disk on Farmer-NAS-VMFS that holds homePool (ZFS).
# Run after vc-login.ps1. Then run scripts/vm/04-zfs-homepool.sh on the VM.
. (Join-Path $PSScriptRoot 'vc-connect.ps1')

$vm = Get-VM spf-datto-pkgs
$ds = Get-Datastore 'Farmer-NAS-VMFS'
"datastore free before: $([math]::Round($ds.FreeSpaceGB)) GB"
$d = New-HardDisk -VM $vm -CapacityGB 3072 -Datastore $ds -StorageFormat Thin -Confirm:$false
"added: $($d.Name)  $($d.CapacityGB) GB  $($d.StorageFormat)  $($d.Filename)"
Get-HardDisk -VM $vm | Select-Object Name, CapacityGB, StorageFormat, Filename | Format-Table -AutoSize
