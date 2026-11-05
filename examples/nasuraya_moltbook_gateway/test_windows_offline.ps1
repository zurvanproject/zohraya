#requires -Version 4.0
# Offline Windows checks. No real keys, HTTP requests or scheduled tasks.
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$path = Join-Path $PSScriptRoot 'windows_moltbook.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Windows bridge did not parse.' }
foreach ($name in @('Get-BridgeDiagnostic','Read-API','Read-Key')) {
    $found = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $false))
    if ($found.Count -ne 1) { throw 'Expected test target function was not found.' }
    . ([scriptblock]::Create($found[0].Extent.Text))
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
Write-Output ('Windows offline checks passed: ' + $script:Checks)
