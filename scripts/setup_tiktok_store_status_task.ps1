<#
    .SYNOPSIS
    Register a Windows Task Scheduler task that checks TikTok store status
    once every 2 days using scripts\run_tiktok_store_status.bat in this repo.

    .DESCRIPTION
    Creates (or replaces) a scheduled task named "HMA-TikTok-Store-Status".
    The task points at run_tiktok_store_status.bat and uses the project root
    as the working directory. By default the task runs only when the current
    user is logged on (InteractiveToken). Pass -RunWhetherLoggedOn to switch
    to S4U so it fires while you are signed out as well.

    .PARAMETER TaskName
    Name shown in Task Scheduler. Default: "HMA-TikTok-Store-Status".

    .PARAMETER RunWhetherLoggedOn
    Use S4U logon type so the task fires whether or not the user is
    signed in. No password is stored.

    .EXAMPLE
    PS> .\scripts\setup_tiktok_store_status_task.ps1

    .EXAMPLE
    PS> .\scripts\setup_tiktok_store_status_task.ps1 -RunWhetherLoggedOn
#>

[CmdletBinding()]
param(
    [string] $TaskName = 'HMA-TikTok-Store-Status',
    [switch] $RunWhetherLoggedOn
)

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BatPath     = Join-Path $ScriptDir 'run_tiktok_store_status.bat'

if (-not (Test-Path -LiteralPath $BatPath)) {
    throw "run_tiktok_store_status.bat not found at $BatPath"
}

$action = New-ScheduledTaskAction `
    -Execute $BatPath `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 2 -At 08:00

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

if ($RunWhetherLoggedOn) {
    $principal = New-ScheduledTaskPrincipal `
        -UserId   ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType S4U `
        -RunLevel Limited
} else {
    $principal = New-ScheduledTaskPrincipal `
        -UserId   ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited
}

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Check TikTok store status (pending balance, on-hold, bank account, account status) every 2 days at 08:00." `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -Principal   $principal `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  Action            : $BatPath"
Write-Host "  Working directory : $ProjectRoot"
Write-Host "  Trigger           : every 2 days at 08:00"
Write-Host "  Execution limit   : 15 minutes"
Write-Host "  Logon mode        : $(if ($RunWhetherLoggedOn) { 'S4U (runs whether logged on or not)' } else { 'Interactive (runs only while logged on)' })"
Write-Host ""
Write-Host "Run once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Then check logs\check_tiktok_store_status.log and logs\tiktok_store_status.bat.log."
