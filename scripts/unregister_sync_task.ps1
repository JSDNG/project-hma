<#
    .SYNOPSIS
    Remove the HMA-Supover-Sync scheduled task.

    .EXAMPLE
    PS> .\scripts\unregister_sync_task.ps1
#>

[CmdletBinding()]
param(
    [string] $TaskName = 'HMA-Supover-Sync'
)

$ErrorActionPreference = 'Stop'

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "No scheduled task named '$TaskName' was found — nothing to do."
    return
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Unregistered scheduled task '$TaskName'."
