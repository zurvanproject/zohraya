#requires -Version 4.0
# Offline Windows checks. No real keys, HTTP requests or scheduled tasks.
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$path = Join-Path $PSScriptRoot 'windows_moltbook.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Windows bridge did not parse.' }
foreach ($name in @('Get-BridgeDiagnostic','Read-API','Read-Key','Read-PythonAPI','Write-Snapshot')) {
    $found = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $false))
    if ($found.Count -ne 1) { throw 'Expected test target function was not found.' }
    $definition = $found[0].Extent.Text
    if ($name -eq 'Read-PythonAPI') {
        # Only synthetic credentials are used in this offline test. Expose child
        # failures here so the regression suite can diagnose process startup.
        $definition = $definition.Replace('$null = $errTask.Result', '$null = $errTask.Result; if ($process.ExitCode -ne 0) { Write-Host ("Offline child output: " + $outTask.Result); Write-Host ("Offline child error: " + $errTask.Result) }')
    }
    . ([scriptblock]::Create($definition))
}
$script:Checks = 0
function Assert-Check([bool]$condition, [string]$label) {
    if (-not $condition) { throw ('Check failed: ' + $label) }
    $script:Checks++
}
$sampleKey = 'OFFLINE_TEST_KEY_NOT_A_REAL_CREDENTIAL'
$script:Calls = 0

# Model a legacy transport that does NOT expose UseBasicParsing.
function Invoke-RestMethod {
    [CmdletBinding()]
    param($Uri, $Headers, $Method, $MaximumRedirection, $TimeoutSec)
    $script:Calls++
    Assert-Check ($Uri -ceq 'https://www.moltbook.com/api/v1/agents/status') 'fixed HTTPS host'
    Assert-Check ($Method -ceq 'GET' -and $MaximumRedirection -eq 0 -and $TimeoutSec -eq 15) 'bounded GET without redirects'
    Assert-Check ($Headers.Authorization -ceq ('Bearer ' + $sampleKey)) 'credential supplied only to fixed request'
    Assert-Check ([Net.ServicePointManager]::SecurityProtocol -eq [Net.SecurityProtocolType]::Tls12) 'TLS 1.2 during request'
    return @{ status = 'claimed' }
}
$before = [Net.ServicePointManager]::SecurityProtocol
$result = Read-API '/api/v1/agents/status' $sampleKey
Assert-Check ($result.status -ceq 'claimed') 'legacy transport succeeds without unsupported switch'
Assert-Check ([Net.ServicePointManager]::SecurityProtocol -eq $before) 'TLS restored on success'
$blocked = $false
try { Read-API '/api/v1/posts' $sampleKey | Out-Null } catch { $blocked = $true }
Assert-Check ($blocked -and $script:Calls -eq 1) 'unapproved route rejected before transport'

Add-Type -TypeDefinition @'
public sealed class OfflineBridgeHttpResponse : System.Net.WebResponse {
    public System.Net.HttpStatusCode StatusCode {
        get { return System.Net.HttpStatusCode.Unauthorized; }
    }
}
public static class OfflineBridgeErrors {
    public static System.Exception Unauthorized(string message) {
        return new System.Net.WebException(message, null,
            System.Net.WebExceptionStatus.ProtocolError, new OfflineBridgeHttpResponse());
    }
    public static System.Exception Timeout(string message) {
        return new System.Net.WebException(message, System.Net.WebExceptionStatus.Timeout);
    }
}
'@
$marker = 'SENSITIVE_EXCEPTION_OR_RESPONSE_MUST_NOT_BE_PRINTED'
$script:FakeFailure = [OfflineBridgeErrors]::Unauthorized($marker)

# Model a transport exposing UseBasicParsing, then fail with a synthetic 401.
function Invoke-RestMethod {
    [CmdletBinding()]
    param($Uri, $Headers, $Method, $MaximumRedirection, $TimeoutSec, [switch]$UseBasicParsing)
    Assert-Check $UseBasicParsing.IsPresent 'basic parsing enabled when available'
    throw $script:FakeFailure
}
$record = $null
try { Read-API '/api/v1/agents/status' $sampleKey | Out-Null } catch { $record = $_ }
Assert-Check ($null -ne $record) 'transport error retained'
Assert-Check ([Net.ServicePointManager]::SecurityProtocol -eq $before) 'TLS restored on failure'
$diagnostic = Get-BridgeDiagnostic $record 'status_request'
Assert-Check ($diagnostic.http_status -eq 401 -and $diagnostic.network_status -eq 'ProtocolError') 'HTTP failure classified'
Assert-Check ($diagnostic.stage -eq 'status_request' -and -not $diagnostic.ok) 'stage retained'
Assert-Check (($diagnostic | ConvertTo-Json -Compress) -notmatch $marker) 'exception and response contents not logged'
$unknown = Get-BridgeDiagnostic $record $marker
Assert-Check ($unknown.stage -eq 'unknown') 'unapproved stage text not logged'
$script:FakeFailure = [OfflineBridgeErrors]::Timeout($marker)
try { Read-API '/api/v1/agents/status' $sampleKey | Out-Null } catch { $record = $_ }
$timeoutDiagnostic = Get-BridgeDiagnostic $record 'status_request'
Assert-Check ($null -eq $timeoutDiagnostic.http_status -and $timeoutDiagnostic.network_status -eq 'Timeout') 'timeout distinguished from HTTP failure'

# Exercise the actual DPAPI read path with an ephemeral synthetic key.
$KeyFile = Join-Path $env:TEMP ('nasuraya-test-' + [guid]::NewGuid().ToString('N'))
try {
    $secure = ConvertTo-SecureString -String $sampleKey -AsPlainText -Force
    [IO.File]::WriteAllText($KeyFile, (ConvertFrom-SecureString $secure), [Text.Encoding]::ASCII)
    $roundTrip = Read-Key
    Assert-Check ($roundTrip -ceq $sampleKey) 'DPAPI key round trip'
    $secure = ConvertTo-SecureString -String 'invalid key with spaces' -AsPlainText -Force
    [IO.File]::WriteAllText($KeyFile, (ConvertFrom-SecureString $secure), [Text.Encoding]::ASCII)
    $rejected = $false
    try { Read-Key | Out-Null } catch { $rejected = $true; $invalid = Get-BridgeDiagnostic $_ $script:BridgeStage }
    Assert-Check ($rejected -and $invalid.stage -eq 'key_format') 'invalid key rejected with nonsecret diagnostic'
} finally {
    if (Test-Path -LiteralPath $KeyFile) { Remove-Item -LiteralPath $KeyFile -Force }
}
# Exercise the real Windows subprocess boundary with a synthetic key and stubbed
# read function. No live HTTP, certifi install, or account credentials required.
$PythonExe = (Get-Command python.exe -ErrorAction Stop).Source
$raw = [IO.File]::ReadAllText($path)
$match = [regex]::Match($raw, "(?s)\`$script:PythonReadOnly = @'\r?\n(.*?)\r?\n'@")
Assert-Check $match.Success 'embedded Python source found'
$originalPython = $match.Groups[1].Value
$script:PythonReadOnly = $originalPython.Replace("if __name__ == '__main__':", 'if False:') + @'

def read_api(route, key):
    assert route == '/api/v1/agents/status'
    assert key == 'OFFLINE_TEST_KEY_NOT_A_REAL_CREDENTIAL'
    return {'status': 'claimed'}
sys.exit(main())
'@
$Transport = 'Python'
$result = Read-API '/api/v1/agents/status' $sampleKey
Assert-Check ($result.status -ceq 'claimed') 'Python subprocess receives route and stdin key'
$script:PythonReadOnly = $originalPython
$record = $null
try { Read-API '/api/v1/agents/status' 'invalid key' | Out-Null } catch { $record = $_ }
Assert-Check ($null -ne $record) 'Python subprocess fails closed on invalid key'
$diagnostic = Get-BridgeDiagnostic $record 'status_request'
Assert-Check ($diagnostic.network_status -ceq 'InvalidData') 'safe Python diagnostic preserved through PowerShell'
Assert-Check (($diagnostic | ConvertTo-Json -Compress) -notmatch $sampleKey) 'subprocess diagnostic omits key'
# A recurring task must replace an existing snapshot, not just create its first
# one. Plain $null in File.Replace's string argument broke this on Windows.
$HomeDir = Join-Path $env:TEMP ('nasuraya-snapshot-test-' + [guid]::NewGuid().ToString('N'))
$SnapshotFile = Join-Path $HomeDir 'public_social_snapshot.json'
New-Item -ItemType Directory -Path $HomeDir | Out-Null
try {
    Write-Snapshot @{ sequence = 1; posts = @() }
    $first = Get-Content -LiteralPath $SnapshotFile -Raw | ConvertFrom-Json
    Assert-Check ($first.sequence -eq 1) 'initial snapshot saved'
    Write-Snapshot @{ sequence = 2; posts = @(@{ id = 'test_post_123' }) }
    $second = Get-Content -LiteralPath $SnapshotFile -Raw | ConvertFrom-Json
    Assert-Check ($second.sequence -eq 2 -and $second.posts.Count -eq 1) 'existing snapshot atomically replaced'
    $lock = [IO.File]::Open($SnapshotFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    $blocked = $false
    try { Write-Snapshot @{ sequence = 3 } } catch { $blocked = $true } finally { $lock.Dispose() }
    Assert-Check $blocked 'locked destination fails without non-atomic fallback'
    $afterFailure = Get-Content -LiteralPath $SnapshotFile -Raw | ConvertFrom-Json
    Assert-Check ($afterFailure.sequence -eq 2) 'failed replacement preserves previous snapshot'
    Assert-Check (@(Get-ChildItem -LiteralPath $HomeDir -Force).Count -eq 1) 'temporary snapshots cleaned after success and failure'
} finally {
    Remove-Item -LiteralPath $HomeDir -Recurse -Force
}
Write-Output ('Windows offline checks passed: ' + $script:Checks)
