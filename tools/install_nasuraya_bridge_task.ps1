# Nasuraya Bridge - install boot-time Windows Scheduled Task.
# Windows Server 2012 R2 / PowerShell 4.0 compatible.
# Does not ask for or reveal the GitHub personal access token.
$ErrorActionPreference = 'Stop'
$taskName = 'NasurayaBridge'
$bridgePath = 'C:\NasurayaBridge\bridge.ps1'
$dpapiPath = Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'
$windowsUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-Object System.Security.Principal.WindowsPrincipal([System.Security.Principal.WindowsIdentity]::GetCurrent())

if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open Windows PowerShell as Administrator before running this installer.'
}
if (-not (Test-Path -LiteralPath $bridgePath)) {
    throw 'The bridge script was not found at C:\NasurayaBridge\bridge.ps1.'
}
if (-not (Test-Path -LiteralPath $dpapiPath)) {
    throw 'The encrypted GitHub token was not found. Run bridge.ps1 -Setup first.'
}

Write-Host ('Installing NasurayaBridge task for Windows account: ' + $windowsUser)
Write-Host 'This is your WINDOWS login password, not the GitHub token.'
Write-Host 'Type it only here on the Windows server; input is hidden.'
$securePassword = Read-Host 'Windows login password' -AsSecureString
if ($securePassword.Length -eq 0) { throw 'No password entered; nothing was registered.' }

$credential = New-Object System.Management.Automation.PSCredential($windowsUser, $securePassword)
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $bridgePath) -WorkingDirectory 'C:\NasurayaBridge'
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
try {
    Register-ScheduledTask -TaskName $taskName -Description 'Bounded GitHub Issues bridge for Nasuraya; starts automatically when Windows boots.' -Action $action -Trigger $trigger -Settings $settings -User $windowsUser -Password $credential.GetNetworkCredential().Password -RunLevel Highest -Force | Out-Null
} finally {
    $credential = $null
    $securePassword = $null
}
Write-Host 'TASK_REGISTERED: NasurayaBridge (at system startup).'
Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
Start-Sleep -Seconds 8
$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Host ('TASK_STATE: {0}; LAST_RESULT: {1}' -f $task.State, $info.LastTaskResult)
Write-Host 'Bridge log file:'
Write-Host (Join-Path $env:ProgramData 'NasurayaBridge\bridge.log')
Write-Host 'The original interactive PowerShell bridge should remain closed after task installation to prevent duplicate polling.'
