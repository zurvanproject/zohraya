#requires -Version 4.0
<#
Nasuraya Moltbook -> Tadash public social snapshot.
Windows only, READ ONLY. No registration, publishing, commands, Tadash memory
access or private data uploads. Uses an existing account key encrypted via DPAPI.
#>
[CmdletBinding()]
param(
    [ValidateSet('Init','Once','Install','Status')]
    [string]$Action = 'Once'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$HomeDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Nasuraya\Moltbook'
$KeyFile = Join-Path $HomeDir 'moltbook_key.dpapi'
$SnapshotFile = Join-Path $HomeDir 'public_social_snapshot.json'
$TaskName = 'NasurayaMoltbookReadOnly'
$script:BridgeStage = 'startup'

function Get-BridgeDiagnostic($record, [string]$stage) {
    # Only fixed labels and numeric metadata may leave this boundary.
    # Do not include Message, ErrorDetails, response bodies or InvocationInfo text.
    $allowedStages = @('startup','private_directory','key_init','key_read','key_format',
        'status_request','validate_claim','identity_request','validate_identity',
        'feed_request','normalize_posts','save_snapshot','task_install','local_status')
    if ($allowedStages -notcontains $stage) { $stage = 'unknown' }
    $errorType = 'Unknown'
    $httpStatus = $null
    $networkStatus = $null
    $current = $record.Exception
    for ($depth = 0; $null -ne $current -and $depth -lt 8; $depth++) {
        $name = $current.GetType().Name
        if ($name -cmatch '^[A-Za-z][A-Za-z0-9_]{0,79}$') { $errorType = $name }
        if ($current -is [Net.WebException]) {
            $networkStatus = $current.Status.ToString()
            try {
                if ($null -ne $current.Response) {
                    $code = [int]$current.Response.StatusCode
                    if ($code -ge 100 -and $code -le 599) { $httpStatus = $code }
                }
            } catch { }
        }
        $current = $current.InnerException
    }
    $line = 0
    if ($null -ne $record.InvocationInfo) { $line = [int]$record.InvocationInfo.ScriptLineNumber }
    return [ordered]@{
        ok = $false
        stage = $stage
        http_status = $httpStatus
        network_status = $networkStatus
        error_type = $errorType
        line = $line
    }
}

function Initialize-PrivateDir {
    if (-not (Test-Path -LiteralPath $HomeDir -PathType Container)) {
        New-Item -ItemType Directory -Path $HomeDir -Force | Out-Null
    }
    $item = Get-Item -LiteralPath $HomeDir -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'State path cannot be a junction or symlink.'
    }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $HomeDir '/inheritance:r' '/grant:r' "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not set private directory ACL.' }
}

function Read-Key {
    if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) {
        throw 'Initialize the EXISTING nasuraya Moltbook API key on this VPS with -Action Init.'
    }
    $item = Get-Item -LiteralPath $KeyFile -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'DPAPI key cannot be a link.'
    }
    $secure = (Get-Content -LiteralPath $KeyFile -Raw -Encoding ASCII).Trim() | ConvertTo-SecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $script:BridgeStage = 'key_format'
    if ($key -cnotmatch '^[A-Za-z0-9_-]{12,256}$') { throw 'Invalid credential format.' }
    return $key
}

function Get-BoundedText($value, [int]$maxChars) {
    if ($null -eq $value -or $value -isnot [string]) { return '' }
    if ($value.Length -gt $maxChars) { return $value.Substring(0, $maxChars) }
    return $value
}

function Read-API([string]$route, [string]$apiKey) {
    if ($route -cnotmatch '^/api/v1/(agents/status|agents/me|posts\?sort=new&limit=10)$') {
        throw 'Only fixed read-only routes are supported.'
    }
    $headers = @{ Authorization = ('Bearer ' + $apiKey); Accept = 'application/json' }
    # PowerShell 4.0 may otherwise default to TLS 1.0 on .NET Framework.
    # Only this request's process state changes; restore it even on failure.
    $previousProtocol = [Net.ServicePointManager]::SecurityProtocol
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        # Keep the fixed host, GET-only method and no-redirect boundary.
        $request = @{
            Uri = ('https://www.moltbook.com' + $route)
            Headers = $headers
            Method = 'GET'
            MaximumRedirection = 0
            TimeoutSec = 15
        }
        # Feature-detect this parameter instead of assuming the host exposes it.
        if ((Get-Command Invoke-RestMethod).Parameters.ContainsKey('UseBasicParsing')) {
            $request.UseBasicParsing = $true
        }
        return Invoke-RestMethod @request
    } finally {
        [Net.ServicePointManager]::SecurityProtocol = $previousProtocol
    }
}

function Write-Snapshot([object]$doc) {
    if (Test-Path -LiteralPath $SnapshotFile) {
        $item = Get-Item -LiteralPath $SnapshotFile -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Snapshot cannot be a link.'
        }
    }
    $tmp = Join-Path $HomeDir ('.snapshot-' + [guid]::NewGuid().ToString('N'))
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($tmp, ($doc | ConvertTo-Json -Depth 8 -Compress), $utf8)
        if (Test-Path -LiteralPath $SnapshotFile) {
            [IO.File]::Replace($tmp, $SnapshotFile, $null)
        } else {
            Move-Item -LiteralPath $tmp -Destination $SnapshotFile
        }
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}

try {
    $script:BridgeStage = 'private_directory'
    Initialize-PrivateDir
    switch ($Action) {
        'Init' {
            $script:BridgeStage = 'key_init'
            if (Test-Path -LiteralPath $KeyFile) { throw 'Encrypted key already exists. Do not register again.' }
            $secret = Read-Host 'Paste EXISTING nasuraya Moltbook API key here on the VPS (hidden)' -AsSecureString
            $encrypted = ConvertFrom-SecureString -SecureString $secret
            $tmp = Join-Path $HomeDir ('.key-' + [guid]::NewGuid().ToString('N'))
            try {
                [IO.File]::WriteAllText($tmp, $encrypted, [Text.Encoding]::ASCII)
                if (Test-Path -LiteralPath $KeyFile) { throw 'Already initialized.' }
                Move-Item -LiteralPath $tmp -Destination $KeyFile
            } finally {
                if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
            }
            Write-Output 'Existing account key encrypted locally using Windows DPAPI. Key not displayed.'
        }
        'Once' {
            $script:BridgeStage = 'key_read'
            $key = Read-Key
            try {
                $script:BridgeStage = 'status_request'
                $status = Read-API '/api/v1/agents/status' $key
                $script:BridgeStage = 'validate_claim'
                if ($status.status -cne 'claimed') { throw 'Agent claim not confirmed.' }
                $script:BridgeStage = 'identity_request'
                $me = Read-API '/api/v1/agents/me' $key
                $script:BridgeStage = 'validate_identity'
                $profile = if ($null -ne $me.agent) { $me.agent } else { $me }
                if ([string]$profile.name -ine 'nasuraya') { throw 'Authenticated identity mismatch.' }
                $script:BridgeStage = 'feed_request'
                $feed = Read-API '/api/v1/posts?sort=new&limit=10' $key
            } finally {
                $key = $null
            }
            $script:BridgeStage = 'normalize_posts'
            $items = New-Object System.Collections.Generic.List[object]
            foreach ($p in @($feed.posts)) {
                if ($null -eq $p) { continue }
                $id = [string]$p.id
                if ($id -cnotmatch '^[A-Za-z0-9_-]{8,128}$') { continue }
                $authorName = ''
                if ($p.author -is [string]) { $authorName = $p.author }
                elseif ($null -ne $p.author) { $authorName = [string]$p.author.name }
                $items.Add(@{
                    id = $id
                    author = (Get-BoundedText $authorName 100)
                    title = (Get-BoundedText $p.title 200)
                    excerpt = (Get-BoundedText $p.content 250)
                })
                if ($items.Count -ge 20) { break }
            }
            $doc = @{
                schema = 'nasuraya-moltbook-public-snapshot/1'
                source = 'https://www.moltbook.com'
                agent = 'nasuraya'
                claim_status = 'claimed'
                checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
                posts = @($items.ToArray())
            }
            $script:BridgeStage = 'save_snapshot'
            Write-Snapshot $doc
            Write-Output (@{ ok = $true; agent = 'nasuraya'; status = 'claimed'; observed_posts = $items.Count; posting_enabled = $false; tadash_private_state_changed = $false } | ConvertTo-Json -Compress)
        }
        'Install' {
            $script:BridgeStage = 'task_install'
            if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) { throw 'Run -Action Init first.' }
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
            $taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Action Once')
            $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
            $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
            # Password logon gives user-bound DPAPI and networking after RDP logoff.
            # Credentials are entered LOCALLY on VPS, never in ChatGPT.
            $creds = Get-Credential -UserName $identity.Name -Message 'Windows account password for scheduled background login'
            if ($null -eq $creds) { throw 'Task setup cancelled.' }
            $windowsPassword = $creds.GetNetworkCredential().Password
            try {
                Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $trigger -Settings $settings -User $identity.Name -Password $windowsPassword -Force | Out-Null
            } finally {
                $windowsPassword = $null
            }
            Write-Output 'Read-only scheduled task installed (every 15 minutes). Check -Action Status.'
        }
        'Status' {
            $script:BridgeStage = 'local_status'
            $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            $file = Get-Item -LiteralPath $SnapshotFile -ErrorAction SilentlyContinue
            Write-Output (@{
                powershell_version = $PSVersionTable.PSVersion.ToString()
                task_installed = ($null -ne $task)
                task_state = if ($null -ne $task) { [string]$task.State } else { 'missing' }
                snapshot_exists = ($null -ne $file)
                snapshot_last_write_utc = if ($null -ne $file) { $file.LastWriteTimeUtc.ToString('o') } else { $null }
                posting_enabled = $false
            } | ConvertTo-Json -Compress)
        }
    }
} catch {
    Write-Output ((Get-BridgeDiagnostic $_ $script:BridgeStage) | ConvertTo-Json -Compress)
    exit 1
}
