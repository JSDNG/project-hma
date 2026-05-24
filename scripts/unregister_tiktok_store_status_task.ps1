<#
    .SYNOPSIS
    Remove the HMA-TikTok-Store-Status scheduled task.

    .EXAMPLE
    PS> .\scripts\unregister_tiktok_store_status_task.ps1
#>

[CmdletBinding()]
param(
    [string] $TaskName = 'HMA-TikTok-Store-Status'
)

$ErrorActionPreference = 'Stop'

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "No scheduled task named '$TaskName' was found - nothing to do."
    return
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Unregistered scheduled task '$TaskName'."
