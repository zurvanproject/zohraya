# Offline Windows checks. No real tasks, network, DPAPI, or credentials.
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$agentSource = Join-Path $repositoryRoot 'tools\bridge_v2.py'
$installerSource = Get-Content (Join-Path $repositoryRoot 'tools\install_bridge_v2.ps1') -Raw
$agentHash = (Get-FileHash $agentSource -Algorithm SHA256).Hash.ToLowerInvariant()
$originalProgramData = $env:ProgramData
$testRoot = Join-Path $env:TEMP ('nasuraya-installer-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$env:ProgramData = Join-Path $testRoot 'data'
New-Item -ItemType Directory -Path (Join-Path $env:ProgramData 'NasurayaBridge') -Force | Out-Null
Set-Content (Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi') 'synthetic-not-a-credential'

function Get-ScheduledTask { param($TaskName) return [pscustomobject]@{State=$script:fakeState} }
function Stop-ScheduledTask { param($TaskName) $script:fakeState='Ready' }
function Start-ScheduledTask {
    param($TaskName)
    $script:fakeState='Running'
    if ($script:makeHealth) {
        $epoch=([DateTime]::UtcNow-[DateTime]'1970-01-01T00:00:00Z').TotalSeconds
        @{poll_ok=$true; utc_epoch=$epoch; pid=1234} | ConvertTo-Json |
            Microsoft.PowerShell.Management\Set-Content (Join-Path $env:ProgramData 'NasurayaBridge\v2_health.json')
    }
}
function Export-ScheduledTask { param($TaskName) return '<Task>synthetic definition</Task>' }
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $OutFile)
    Copy-Item -LiteralPath $agentSource -Destination $OutFile
}
function Start-Sleep { param($Seconds) }
function Set-Content {
    param($LiteralPath, [Parameter(ValueFromPipeline=$true)]$Value, $Encoding)
    if ($script:failWrite -and $LiteralPath -eq $script:targetPath) {
        $script:failWrite=$false
        [IO.File]::WriteAllText($LiteralPath, 'partial wrapper')
        throw 'Synthetic partial wrapper write'
    }
    Microsoft.PowerShell.Management\Set-Content -LiteralPath $LiteralPath -Value $Value -Encoding $Encoding
}

try {
    foreach ($scenario in @('success', 'partial-write', 'no-health')) {
        $caseRoot = Join-Path $testRoot $scenario
        New-Item -ItemType Directory -Path $caseRoot | Out-Null
        $script:targetPath=Join-Path $caseRoot 'bridge.ps1'
        [IO.File]::WriteAllText($script:targetPath, '# original v1 bridge')
        [IO.File]::WriteAllText((Join-Path $caseRoot 'bridge_v2.py'), '# previous agent')
        $script:fakeState='Running'
        $script:failWrite=$scenario -eq 'partial-write'
        $script:makeHealth=$scenario -eq 'success'
        Remove-Item (Join-Path $env:ProgramData 'NasurayaBridge\v2_health.json') -ErrorAction SilentlyContinue
        $source=$installerSource.Replace("'C:\NasurayaBridge'", ("'"+$caseRoot.Replace("'","''")+"'"))
        $source=[regex]::Replace($source, "(?m)^\`$expectedSha256 = '[a-f0-9]+'", ("`$expectedSha256 = '"+$agentHash+"'"))
        $failed=$false
        try { & ([scriptblock]::Create($source)) } catch { $failed=$true }
        $backups=@(Get-ChildItem $caseRoot -Filter 'bridge_backup_*.ps1')
        if ($backups.Count -ne 1 -or (Get-Content $backups[0].FullName -Raw).Trim() -ne '# original v1 bridge') {
            throw "Backup verification failed: $scenario"
        }
        if ($scenario -eq 'success') {
            if ($failed -or (Get-Content $script:targetPath -Raw) -notmatch 'Bridge v2 Windows') {
                throw 'Successful installer scenario failed'
            }
        } else {
            if (-not $failed -or (Get-Content $script:targetPath -Raw).Trim() -ne '# original v1 bridge' -or
                (Get-Content (Join-Path $caseRoot 'bridge_v2.py') -Raw).Trim() -ne '# previous agent' -or
                $script:fakeState -ne 'Running') { throw "Rollback failed: $scenario" }
        }
        Write-Host ('PASS installer scenario: '+$scenario)
    }
} finally {
    $env:ProgramData=$originalProgramData
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
