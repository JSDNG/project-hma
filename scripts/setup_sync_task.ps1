<#
    .SYNOPSIS
    Register a Windows Task Scheduler task that runs the Supover sync twice
    a day (00:00 and 12:00) using scripts\run_sync.bat in this repo.

    .DESCRIPTION
    Creates (or replaces) a scheduled task named "HMA-Supover-Sync". The
    task points at the run_sync.bat shipped alongside this script and uses
    the project root as the working directory. By default the task runs
    only when the current user is logged on (InteractiveToken). Pass
    -RunWhetherLoggedOn to switch to S4U so it fires while you are signed
    out as well — Supover is a public endpoint, so the network restriction
    that S4U normally imposes does not block this job.

    .PARAMETER TaskName
    Name shown in Task Scheduler. Default: "HMA-Supover-Sync".

    .PARAMETER RunWhetherLoggedOn
    Use S4U logon type so the task fires whether or not the user is
    signed in. No password is stored.

    .EXAMPLE
    PS> .\scripts\setup_sync_task.ps1

    .EXAMPLE
    PS> .\scripts\setup_sync_task.ps1 -RunWhetherLoggedOn
#>

[CmdletBinding()]
param(
    [string] $TaskName = 'HMA-Supover-Sync',
    [switch] $RunWhetherLoggedOn
)

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BatPath     = Join-Path $ScriptDir 'run_sync.bat'

if (-not (Test-Path -LiteralPath $BatPath)) {
    throw "run_sync.bat not found at $BatPath"
}

$action = New-ScheduledTaskAction `
    -Execute $BatPath `
    -WorkingDirectory $ProjectRoot

$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 00:00),
    (New-ScheduledTaskTrigger -Daily -At 12:00)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

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
    -Description "Push HMA profiles to Supover twice a day (00:00 / 12:00)." `
    -Action      $action `
    -Trigger     $triggers `
    -Settings    $settings `
    -Principal   $principal `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  Action            : $BatPath"
Write-Host "  Working directory : $ProjectRoot"
Write-Host "  Triggers          : daily 00:00 and 12:00"
Write-Host "  Logon mode        : $(if ($RunWhetherLoggedOn) { 'S4U (runs whether logged on or not)' } else { 'Interactive (runs only while logged on)' })"
Write-Host ""
Write-Host "Run once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Then check logs\supover_sync.log and logs\supover_sync.bat.log."
