# Nasuraya Bridge v2: guarded recovery for Windows Server 2012 R2 / PowerShell 4.
# Usage: .\nasu_migration_bridge_recovery.ps1 -RecoverIfSafe
# Default is read-only. With -RecoverIfSafe the ONLY mutation is Start-ScheduledTask,
# gated on local journal, public GitHub queue, pinned agent, and task state.
# Never changes Bridge code, task definition, journal, queued commands, or secrets.
param([switch]$RecoverIfSafe)
$ErrorActionPreference = 'Stop'
$repo = 'zurvanproject/zohraya'
$owner = 'zurvanproject'
$taskName = 'NasurayaBridge'
$root = Join-Path $env:ProgramData 'NasurayaBridge'
$journalFile = Join-Path $root 'v2_journal.json'
$healthFile = Join-Path $root 'v2_health.json'
$wrapperFile = 'C:\NasurayaBridge\bridge.ps1'
$agentFile = 'C:\NasurayaBridge\bridge_v2.py'
$expectedAgentHash = '9d42e61d4751d713daeac1eb4ce3569b90c2a90716e69b0b6c3f4d9c8cc5a93e'
$anchorId = 'comment-6740249936'
$allowed = @{}
$allowed['comment-6876709804'] = '5d4ce312933a0e55575e05d66a525438b8c6c49e nasu_awake_status bd44167423248069f5b405e4b71cf0687ac89760a7827c18c917bbb4a2f7e2e5'
$allowed['comment-6876711085'] = '90692bde9f1e4b5b7f311162b7c83127715df710 nasu_awake_ingress_status ef9743df8142f6dc22a73809920ff542c52af4b7e508f2cce2edd504153f8e8b'
$allowed['comment-6876939706'] = '0648f729f03f6a48b40e060d53ef4cf643544bf3 nasu_migration_inventory e0cf2b2cbb090f572a9b314d0a4320b7f895d0a0971fae788fe29bd1c324bf2c'

function Say([string]$line) { Write-Output $line }
function Get-JsonPublic([string]$url) {
    # The original bridge bypasses proxies and uses TLS verification.
    $req = [System.Net.HttpWebRequest][System.Net.WebRequest]::Create($url)
    $req.Method = 'GET'; $req.Proxy = $null; $req.Timeout = 15000
    $req.ReadWriteTimeout = 15000
    $req.UserAgent = 'Nasuraya-GuardedRecovery-ReadOnly/1'
    $req.Accept = 'application/vnd.github+json'
    $response = $req.GetResponse()
    try {
        $reader = New-Object System.IO.StreamReader -ArgumentList @($response.GetResponseStream(), [Text.Encoding]::UTF8)
        try { $raw = $reader.ReadToEnd() }
        finally { $reader.Close() }
        if ($raw.Length -gt 1000000) { throw 'ResponseTooLarge' }
        return (ConvertFrom-Json -InputObject $raw)
    } finally { $response.Close() }
}
function JournalRecord([object]$journal, [string]$id) {
    $property = $journal.PSObject.Properties[$id]
    if ($null -eq $property) { return $null }
    return $property.Value
}
function EpochUtc([double]$epoch) {
    return ([DateTime]'1970-01-01').AddSeconds($epoch)
}
function ReadQueue() {
    $issue = Get-JsonPublic ('https://api.github.com/repos/' + $repo + '/issues/149')
    if ($issue.state -ne 'open' -or $issue.user.login -ne $owner) { throw 'IssueIdentityOrStateMismatch' }
    $requests = @{}; $receipts = @{}; $count = 0; $finished = $false
    for ($page = 1; $page -le 10; $page++) {
        $url = 'https://api.github.com/repos/' + $repo + '/issues/149/comments?per_page=100&page=' + $page
        $items = @(Get-JsonPublic $url)
        foreach ($comment in $items) {
            $count++
            if ($comment.user.login -ne $owner) { continue }
            $body = ([string]$comment.body).Trim()
            $match = [regex]::Match($body, '\Anasu: run ([0-9a-f]{40}) ([a-z][a-z0-9_]{1,39}) ([0-9a-f]{64})\z')
            if ($match.Success) {
                $key = 'comment-' + [string]$comment.id
                $requests[$key] = $match.Groups[1].Value + ' ' + $match.Groups[2].Value + ' ' + $match.Groups[3].Value
                continue
            }
            $reply = [regex]::Match($body.Replace("`r", ''), '\ANasuraya Bridge v2 result; request_id=(comment-[0-9]+); command=run ([a-z][a-z0-9_]{1,39})\nResult: ')
            if ($reply.Success) {
                $receipts[$reply.Groups[1].Value] = $reply.Groups[2].Value
            }
        }
        if ($items.Count -lt 100) { $finished = $true; break }
    }
    if (-not $finished) { throw 'QueuePaginationIncomplete' }
    return @{ Requests = $requests; Receipts = $receipts; CommentCount = $count }
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Say ('MODE=' + $(if ($RecoverIfSafe) {'RECOVER_IF_SAFE'} else {'INSPECT_ONLY'}))
    if (-not (Test-Path -LiteralPath $agentFile -PathType Leaf)) { throw 'V2AgentMissing' }
    if (-not (Test-Path -LiteralPath $wrapperFile -PathType Leaf)) { throw 'V2WrapperMissing' }
    $actualHash = (Get-FileHash -LiteralPath $agentFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedAgentHash) { throw 'BridgeAgentPinMismatch' }
    $wrapper = [IO.File]::ReadAllText($wrapperFile)
    if (-not $wrapper.Contains('bridge_v2.py')) { throw 'V2WrapperNotActive' }
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
    $taskState = [string]$task.State
    $actions = ($task.Actions | ForEach-Object { [string]$_.Execute + ' ' + [string]$_.Arguments }) -join ' '
    if ($actions -notmatch 'bridge\.ps1') { throw 'TaskActionNotBridgeWrapper' }
    Say ('TASK_STATE=' + $taskState + ';LAST_RESULT=' + [string]$info.LastTaskResult)
    if (-not (Test-Path -LiteralPath $journalFile -PathType Leaf)) { throw 'JournalMissing' }
    $journal = Get-Content -LiteralPath $journalFile -Raw | ConvertFrom-Json
    if ($null -eq $journal -or $null -eq $journal.PSObject) { throw 'JournalInvalid' }
    $anchor = JournalRecord $journal $anchorId
    if ($null -eq $anchor -or [string]$anchor.state -ne 'posted') { throw 'JournalContinuityNotProven' }

    $lastPoll = 'UNKNOWN'
    $livePid = $false
    if (Test-Path -LiteralPath $healthFile -PathType Leaf) {
        $health = Get-Content -LiteralPath $healthFile -Raw | ConvertFrom-Json
        if ($null -ne $health.utc_epoch) {
            $lastPoll = [string][Math]::Round(((Get-Date).ToUniversalTime() - (EpochUtc ([double]$health.utc_epoch))).TotalMinutes, 1)
        }
        if ($null -ne $health.pid) {
            try { $livePid = $null -ne (Get-Process -Id ([int]$health.pid) -ErrorAction Stop) }
            catch { $livePid = $false }
        }
    }
    Say ('HEALTH_AGE_MIN=' + $lastPoll + ';HEALTH_PID_EXISTS=' + $livePid)
    $bridgeProcesses = @(Get-WmiObject -Class Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop | Where-Object { [string]$_.CommandLine -match 'bridge_v2\.py' })
    Say ('LIVE_BRIDGE_PROCESSES=' + $bridgeProcesses.Count)

    $queue = ReadQueue
    Say ('GITHUB=REACHABLE;COMMENTS=' + $queue.CommentCount + ';VALID_COMMANDS=' + $queue.Requests.Count + ';RECEIPTS=' + $queue.Receipts.Count)
    $unsafe = 0; $unanswered = 0
    foreach ($id in @($queue.Requests.Keys)) {
        $cmd = [string]$queue.Requests[$id]
        $parts = $cmd.Split(' ')
        $name = $parts[1]
        if ($queue.Receipts.ContainsKey($id)) {
            if ($queue.Receipts[$id] -ne $name) { Say ('MISMATCH_RECEIPT=' + $id); $unsafe++ }
            continue
        }
        $unanswered++
        $entry = JournalRecord $journal $id
        $state = if ($null -eq $entry) { 'ABSENT' } else { [string]$entry.state }
        $known = $allowed.ContainsKey($id) -and $cmd -ceq [string]$allowed[$id]
        Say ('PENDING=' + $id + ';JOB=' + $name + ';LOCAL_STATE=' + $state + ';PINNED_KNOWN=' + $known)
        if ($null -ne $entry -and ([string]$entry.job -cne $name)) { $unsafe++; continue }
        if ($state -in @('started', 'pending_post', 'posted')) { continue }
        # Only the three exact migration read/inventory commands may be executed for the FIRST time.
        # A posted anchor in an intact journal proves v2 continuity before these commands.
        if ($state -eq 'ABSENT' -and $known) { continue }
        $unsafe++
    }
    foreach ($id in @($allowed.Keys)) {
        if (-not $queue.Requests.ContainsKey($id)) {
            # Do not act if an exact migration command was edited/removed meanwhile.
            Say ('ORIGINAL_REQUEST_MISSING=' + $id)
            $unsafe++
        } elseif ($queue.Requests[$id] -cne $allowed[$id]) {
            Say ('ORIGINAL_REQUEST_CHANGED=' + $id)
            $unsafe++
        }
    }
    Say ('QUEUE_UNANSWERED=' + $unanswered + ';UNSAFE_TO_RESUME=' + $unsafe)

    $researchState = Join-Path $root 'nasu_24h_20261109_v1\state.json'
    if (Test-Path -LiteralPath $researchState -PathType Leaf) {
        try {
            $research = Get-Content -LiteralPath $researchState -Raw | ConvertFrom-Json
            Say ('RESEARCH_STATUS=' + [string]$research.status + ';STOP_FLAG=' + [string](Test-Path -LiteralPath (Join-Path $root 'nasu_24h_20261109_v1\STOP')))
        } catch { Say 'RESEARCH_STATUS=READ_FAILED' }
    }
    $receipt = Join-Path $root 'video241_v1\receipt.json'
    Say ('FFMPEG_LOCAL_RECEIPT_EXISTS=' + [string](Test-Path -LiteralPath $receipt -PathType Leaf))
    if (-not $RecoverIfSafe) { Say 'NEXT=INSPECT_ONLY_NO_CHANGES'; exit 0 }
    if ($unsafe -ne 0) { throw 'UnresolvedQueueRisk' }
    if ($taskState -ne 'Ready') { throw 'TaskNotReadyToStartWithoutInterruption' }
    if ($livePid -or $bridgeProcesses.Count -ne 0) { throw 'BridgeProcessStillActive' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'AdminRequiredToStartExistingTask' }
    # No Stop-ScheduledTask, no task edits, no journal edits, no changes to the bridge agent.
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Say 'RECOVERY=EXISTING_TASK_START_REQUESTED;NO_JOB_REPLAY_REQUESTED'
    Say 'CONFIRM=CHECK_FRESH_V2_HEALTH_AND_THREE_MIGRATION_JOURNAL_ENTRIES_AFTER_POLL'
    exit 0
} catch {
    # Avoid output of exception messages/paths/URLs that might include sensitive info.
    $reason = [string]$_.Exception.Message
    if ($reason -match '\A(?:ResponseTooLarge|IssueIdentityOrStateMismatch|QueuePaginationIncomplete|V2AgentMissing|V2WrapperMissing|BridgeAgentPinMismatch|V2WrapperNotActive|TaskActionNotBridgeWrapper|JournalMissing|JournalInvalid|JournalContinuityNotProven|UnresolvedQueueRisk|TaskNotReadyToStartWithoutInterruption|BridgeProcessStillActive|AdminRequiredToStartExistingTask)\z') {
        Say ('RECOVERY=BLOCKED;REASON=' + $reason)
    } else {
        Say ('RECOVERY=BLOCKED;ERROR=' + [string]$_.Exception.GetType().Name)
    }
    Say 'NO_MUTATION_PERFORMED_UNLESS_EXISTING_TASK_START_REQUESTED_WAS_PRINTED'
    exit 2
}
