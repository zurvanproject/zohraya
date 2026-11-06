# Nasuraya Bridge v2 installer. One-time activation by the server owner.
# No new GitHub token or Windows password required; preserves existing Task Scheduler identity.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = 'C:\NasurayaBridge'
$target = Join-Path $root 'bridge.ps1'
$agent = Join-Path $root 'bridge_v2.py'
$backup = Join-Path $root 'bridge_v1_backup.ps1'
$task = 'NasurayaBridge'
$expectedSha256 = 'a2e5b05a7e78fc7044c0dd8cd955d6508d1eafaf2c02236a4392fbdc5e5981fd'
$source = 'https://raw.githubusercontent.com/zurvanproject/zohraya/nasuraya/bridge-control-v2/tools/bridge_v2.py'

if (-not (Test-Path -LiteralPath $target)) { throw 'Existing bridge.ps1 not found; nothing changed.' }
if (-not (Test-Path -LiteralPath (Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'))) {
    throw 'Encrypted GitHub token not found; nothing changed.'
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run in the existing Administrator PowerShell window.'
}
$existingTask = Get-ScheduledTask -TaskName $task -ErrorAction Stop

# A newly installed Python can appear in the Task Scheduler environment but not
# in this already-open Administrator PowerShell. Refresh PATH and search common
# user installations and PEP 514 registry locations before failing.
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path = ($machinePath + ';' + $userPath)
$candidates = New-Object 'System.Collections.Generic.List[string]'
$command = Get-Command python.exe -ErrorAction SilentlyContinue
if ($null -ne $command -and $command.Source) { [void]$candidates.Add($command.Source) }
$knownPaths = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    'C:\Python312\python.exe',
    'C:\Program Files\Python312\python.exe',
    'C:\Program Files (x86)\Python312\python.exe'
)
foreach ($candidate in $knownPaths) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { [void]$candidates.Add($candidate) }
}
$roots = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
    (Join-Path $env:ProgramFiles 'Python')
)
foreach ($base in $roots) {
    if (-not (Test-Path -LiteralPath $base)) { continue }
    foreach ($candidate in (Get-ChildItem -Path (Join-Path $base 'Python*\python.exe') -ErrorAction SilentlyContinue)) {
        [void]$candidates.Add($candidate.FullName)
    }
}
$registryRoots = @(
    'HKCU:\Software\Python\PythonCore',
    'HKLM:\Software\Python\PythonCore',
    'HKLM:\Software\WOW6432Node\Python\PythonCore'
)
foreach ($base in $registryRoots) {
    if (-not (Test-Path $base)) { continue }
    foreach ($key in (Get-ChildItem $base -ErrorAction SilentlyContinue)) {
        $installKey = Join-Path $key.PSPath 'InstallPath'
        if (-not (Test-Path $installKey)) { continue }
        $install = Get-Item $installKey -ErrorAction SilentlyContinue
        if ($null -eq $install) { continue }
        $exe = $install.GetValue('ExecutablePath')
        if (-not $exe) {
            $folder = $install.GetValue('')
            if ($folder) { $exe = Join-Path $folder 'python.exe' }
        }
        if ($exe) { [void]$candidates.Add([string]$exe) }
    }
}
$python = $null
$version = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $v = (& $candidate -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $v -match '^(3\.(1[0-9]|[2-9][0-9])\.[0-9]+)

$tmpAgent = $agent + '.new'
Invoke-WebRequest -UseBasicParsing -Uri $source -OutFile $tmpAgent -ErrorAction Stop
$actualHash = (Get-FileHash -LiteralPath $tmpAgent -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedSha256) {
    Remove-Item -LiteralPath $tmpAgent -Force -ErrorAction SilentlyContinue
    throw 'Agent SHA256 verification failed; existing bridge unchanged.'
}

$wrapper = @'
# Nasuraya Bridge v2 Windows scheduled-task wrapper. PowerShell 4 compatible.
$ErrorActionPreference = 'Stop'
$root = 'C:\NasurayaBridge'
$protected = Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'
$secure = ConvertTo-SecureString ((Get-Content -LiteralPath $protected -Raw).Trim())
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:NASURAYA_GH_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
try {
    $exe = '__NASURAYA_PYTHON_EXE__'
    & $exe -I -u (Join-Path $root 'bridge_v2.py') 2>&1 | Out-File -Append -Encoding UTF8 -FilePath (Join-Path $env:ProgramData 'NasurayaBridge\bridge_v2.log')
    if ($LASTEXITCODE -ne 0) { throw 'Nasuraya Python bridge stopped unexpectedly.' }
} finally {
    Remove-Item Env:\NASURAYA_GH_TOKEN -ErrorAction SilentlyContinue
}
'@
$wrapper = $wrapper.Replace('__NASURAYA_PYTHON_EXE__', $python.Replace("'", "''"))
$tokens = $null; $parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($wrapper, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Wrapper PowerShell parse failed; existing bridge unchanged.' }

# All preflight checks have passed. Only now replace the scheduled-task target.
$updated = $false
try {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $target -Destination $backup -Force
    Move-Item -LiteralPath $tmpAgent -Destination $agent -Force
    Set-Content -LiteralPath $target -Value $wrapper -Encoding ASCII
    $updated = $true
    Start-ScheduledTask -TaskName $task -ErrorAction Stop
    Start-Sleep -Seconds 8
    $state = (Get-ScheduledTask -TaskName $task).State.ToString()
    if ($state -ne 'Running') { throw ('Scheduled task is ' + $state) }
    Write-Host ('NASURAYA_V2_STARTED; Python=' + $version + '; Task=' + $state)
    Write-Host 'NEXT: Future bounded jobs will be submitted through GitHub, without more server pastes.'
} catch {
    if ($updated -and (Test-Path -LiteralPath $backup)) {
        Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
        Copy-Item -LiteralPath $backup -Destination $target -Force
        Start-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    }
    throw
}
) {
            $python = $candidate
            $version = $v
            break
        }
    } catch { continue }
}
if (-not $python) {
    throw 'Python 3.10+ not found in the refreshed PATH, registry, or common install folders. Existing bridge is unchanged.'
}
Write-Host ('FOUND_PYTHON: ' + $version)

$tmpAgent = $agent + '.new'
Invoke-WebRequest -UseBasicParsing -Uri $source -OutFile $tmpAgent -ErrorAction Stop
$actualHash = (Get-FileHash -LiteralPath $tmpAgent -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedSha256) {
    Remove-Item -LiteralPath $tmpAgent -Force -ErrorAction SilentlyContinue
    throw 'Agent SHA256 verification failed; existing bridge unchanged.'
}

$wrapper = @'
# Nasuraya Bridge v2 Windows scheduled-task wrapper. PowerShell 4 compatible.
$ErrorActionPreference = 'Stop'
$root = 'C:\NasurayaBridge'
$protected = Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'
$secure = ConvertTo-SecureString ((Get-Content -LiteralPath $protected -Raw).Trim())
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:NASURAYA_GH_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
try {
    $exe = (Get-Command python.exe -ErrorAction Stop).Source
    & $exe -I -u (Join-Path $root 'bridge_v2.py') 2>&1 | Out-File -Append -Encoding UTF8 -FilePath (Join-Path $env:ProgramData 'NasurayaBridge\bridge_v2.log')
    if ($LASTEXITCODE -ne 0) { throw 'Nasuraya Python bridge stopped unexpectedly.' }
} finally {
    Remove-Item Env:\NASURAYA_GH_TOKEN -ErrorAction SilentlyContinue
}
'@
$tokens = $null; $parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($wrapper, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Wrapper PowerShell parse failed; existing bridge unchanged.' }

# All preflight checks have passed. Only now replace the scheduled-task target.
$updated = $false
try {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $target -Destination $backup -Force
    Move-Item -LiteralPath $tmpAgent -Destination $agent -Force
    Set-Content -LiteralPath $target -Value $wrapper -Encoding ASCII
    $updated = $true
    Start-ScheduledTask -TaskName $task -ErrorAction Stop
    Start-Sleep -Seconds 8
    $state = (Get-ScheduledTask -TaskName $task).State.ToString()
    if ($state -ne 'Running') { throw ('Scheduled task is ' + $state) }
    Write-Host ('NASURAYA_V2_STARTED; Python=' + $version + '; Task=' + $state)
    Write-Host 'NEXT: Future bounded jobs will be submitted through GitHub, without more server pastes.'
} catch {
    if ($updated -and (Test-Path -LiteralPath $backup)) {
        Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
        Copy-Item -LiteralPath $backup -Destination $target -Force
        Start-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    }
    throw
}
