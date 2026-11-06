# Nasuraya Bridge v1.0 - bounded, read-only GitHub Issues relay
# Compatible with Windows PowerShell 4.0 / Windows Server 2012 R2.
# Uses only outbound HTTPS, and processes commands from repository owner.
param(
    [switch]$Setup,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = 'zurvanproject/zohraya'
$IssueNumber = 149
$Owner = 'zurvanproject'
$Root = Join-Path $env:ProgramData 'NasurayaBridge'
$TokenFile = Join-Path $Root 'github_token.dpapi'
$SeenFile = Join-Path $Root 'seen.json'
$LogFile = Join-Path $Root 'bridge.log'
$ApiBase = 'https://api.github.com'

if (-not (Test-Path $Root)) { New-Item -ItemType Directory -Path $Root -Force | Out-Null }

function Write-BridgeLog([string]$message) {
    $line = ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message)
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Get-TokenFromSecureString([Security.SecureString]$secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Invoke-GitHub([string]$method, [string]$path, [object]$payload = $null) {
    $headers = @{
        Authorization = ('Bearer ' + $script:Token)
        Accept = 'application/vnd.github+json'
        'User-Agent' = 'NasurayaBridge-v1'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    $args = @{ Uri = ($ApiBase + $path); Method = $method; Headers = $headers; TimeoutSec = 30 }
    if ($null -ne $payload) {
        $args['ContentType'] = 'application/json'
        $args['Body'] = ConvertTo-Json -InputObject $payload -Compress -Depth 5
    }
    return Invoke-RestMethod @args
}

function Get-BridgeAnswer([string]$command) {
    switch ($command) {
        'status' {
            $os = Get-WmiObject Win32_OperatingSystem
            return ('BRIDGE_CONNECTED; OS={0}; version={1}; PS={2}; UTC={3}' -f $os.Caption, $os.Version, $PSVersionTable.PSVersion.ToString(), [DateTime]::UtcNow.ToString('o'))
        }
        'task' {
            try {
                $task = Get-ScheduledTask -TaskName 'NasurayaMoltbookReadOnly' -ErrorAction Stop
                $info = $task | Get-ScheduledTaskInfo
                return ('Task=NasurayaMoltbookReadOnly; state={0}; last_result={1}; last_run={2}' -f $task.State, $info.LastTaskResult, $info.LastRunTime)
            } catch {
                return 'Task NasurayaMoltbookReadOnly not found or unavailable.'
            }
        }
        'disk' {
            $disks = @(Get-WmiObject Win32_LogicalDisk -Filter 'DriveType=3')
            $lines = @()
            foreach ($d in $disks) {
                $lines += ('{0} free_GiB={1:N1} total_GiB={2:N1}' -f $d.DeviceID, ($d.FreeSpace/1GB), ($d.Size/1GB))
            }
            return ($lines -join '; ')
        }
        'python' {
            $python = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($null -eq $python) { return 'Python was not found on PATH.' }
            try { return ((& python.exe --version 2>&1 | Out-String).Trim()) }
            catch { return 'Python invocation failed.' }
        }
        'help' {
            return 'Allowed commands: status, task, disk, python, help. No shell execution, downloads, or file access.'
        }
        default { return 'Command not allowed.' }
    }
}

function Read-Seen {
    $seen = @{}
    if (Test-Path $SeenFile) {
        try {
            $entries = @(Get-Content -Path $SeenFile -Raw | ConvertFrom-Json)
            foreach ($entry in $entries) { if ($entry) { $seen[[string]$entry] = $true } }
        } catch {
            Write-BridgeLog 'Could not parse seen.json; not processing pending requests to avoid duplicates.'
            throw
        }
    }
    return $seen
}

function Save-Seen([hashtable]$seen) {
    $keys = @($seen.Keys | Sort-Object)
    ConvertTo-Json -InputObject $keys -Compress | Set-Content -Path $SeenFile -Encoding UTF8
}

function Process-Request([string]$id, [string]$cmd, [hashtable]$seen) {
    if ($seen.ContainsKey($id)) { return }
    $answer = Get-BridgeAnswer $cmd
    $body = ('Nasuraya Bridge v1 result; request_id={0}; command={1}' -f $id, $cmd) + [Environment]::NewLine + 'Result: ' + $answer
    $null = Invoke-GitHub 'Post' ('/repos/{0}/issues/{1}/comments' -f $Repo, $IssueNumber) @{ body = $body }
    $seen[$id] = $true
    Save-Seen $seen
    Write-BridgeLog ('Completed request {0} ({1})' -f $id, $cmd)
}

function Poll-Bridge {
    $seen = Read-Seen
    $issue = Invoke-GitHub 'Get' ('/repos/{0}/issues/{1}' -f $Repo, $IssueNumber)
    if ($issue.state -ne 'open') {
        Write-BridgeLog 'Bridge issue is closed; no commands accepted.'
        return
    }
    if ($issue.user.login -ne $Owner) {
        throw 'Bridge issue owner does not match.'
    }

    # Load every comment before dispatching commands. This allows us to find
    # completed responses, avoiding duplicates even if local state is lost.
    $allComments = New-Object System.Collections.ArrayList
    $page = 1
    do {
        $path = ('/repos/{0}/issues/{1}/comments?per_page=100&page={2}' -f $Repo, $IssueNumber, $page)
        $response = Invoke-GitHub 'Get' $path
        $pageComments = @($response)
        if ($pageComments.Count -eq 1 -and $pageComments[0] -is [array]) {
            $pageComments = @($pageComments[0])
        }
        foreach ($c in $pageComments) {
            if ($null -ne $c) { [void]$allComments.Add($c) }
        }
        $page = $page + 1
    } while ($pageComments.Count -eq 100)

    $completed = @{}
    foreach ($c in $allComments) {
        if ([string]$c.user.login -ne $Owner) { continue }
        $answerMatch = [regex]::Match([string]$c.body, 'request_id=(issue-initial|comment-[0-9]+);')
        if ($answerMatch.Success) {
            $completed[[string]$answerMatch.Groups[1].Value] = $true
        }
    }
    Write-BridgeLog ('Poll: {0} comments; {1} completed requests' -f $allComments.Count, $completed.Count)

    $initial = [regex]::Match([string]$issue.body, '(?m)^[ \t]*nasu:[ \t]*(status|task|disk|python|help)[ \t]*$')
    if ($initial.Success -and (-not $completed.ContainsKey('issue-initial'))) {
        Process-Request 'issue-initial' $initial.Groups[1].Value.ToLowerInvariant() $seen
    }

    foreach ($c in $allComments) {
        if ([string]$c.user.login -ne $Owner) { continue }
        $cmdMatch = [regex]::Match([string]$c.body, '(?m)^[ \t]*nasu:[ \t]*(status|task|disk|python|help)[ \t]*$')
        if (-not $cmdMatch.Success) { continue }
        $requestId = 'comment-' + [string]$c.id
        if ($completed.ContainsKey($requestId)) { continue }
        $cmd = $cmdMatch.Groups[1].Value.ToLowerInvariant()
        Write-BridgeLog ('Processing request {0}: {1}' -f $requestId, $cmd)
        Process-Request $requestId $cmd $seen
    }
}

if ($Setup) {
    Write-Host 'Nasuraya Bridge setup. Create a fine-grained GitHub token scoped to zurvanproject/zohraya with Issues: Read and write.'
    Write-Host 'Paste your token here, NOT in ChatGPT. The token is stored encrypted for this Windows account.'
    $secure = Read-Host 'GitHub token' -AsSecureString
    $script:Token = Get-TokenFromSecureString $secure
    $me = Invoke-GitHub 'Get' '/user'
    if ($me.login -ne $Owner) {
        throw 'The GitHub token does not belong to the expected repository owner.'
    }
    $secure | ConvertFrom-SecureString | Set-Content -Path $TokenFile -Encoding ASCII
    Write-BridgeLog 'GitHub authentication completed. Token stored with Windows user DPAPI.'
} else {
    if (-not (Test-Path $TokenFile)) {
        throw 'No token configured. Run this script with -Setup first.'
    }
    $encrypted = Get-Content -Path $TokenFile -Raw
    $secure = ConvertTo-SecureString $encrypted.Trim()
    $script:Token = Get-TokenFromSecureString $secure
}

Write-BridgeLog 'Bridge started (bounded read-only commands only).'
do {
    try {
        Poll-Bridge
    } catch {
        Write-BridgeLog ('Poll failed: ' + $_.Exception.Message)
    }
    if (-not $Once) {
        Start-Sleep -Seconds 60
    }
} while (-not $Once)
