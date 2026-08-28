[CmdletBinding()]
param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputDir = Join-Path $RepoRoot "output\release"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

if (-not $OutputPath) {
    $OutputPath = Join-Path $OutputDir ("portal-runtime-{0}.tar.gz" -f (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss"))
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$Stage = Join-Path ([IO.Path]::GetTempPath()) ("portal-runtime-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path (Join-Path $Stage "web_dist") -Force | Out-Null
    $paths = @(
        "api/accounts.py", "api/admin_portal.py", "api/ai.py", "api/billing.py", "api/image_tasks.py",
        "contracts/admin_portal.py", "contracts/portal.py", "services/config.py",
        "services/image_task_service.py", "services/image_task_view.py", "services/portal_billing.py",
        "services/protocol/conversation.py", "services/protocol/openai_v1_chat_complete.py",
        "services/protocol/openai_v1_response.py", "services/storage/portal_repository.py"
    )
    foreach ($path in $paths) {
        $source = Join-Path $RepoRoot $path
        $destination = Join-Path $Stage $path
        New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    Copy-Item -Path (Join-Path $RepoRoot "web-vue\dist\*") -Destination (Join-Path $Stage "web_dist") -Recurse -Force
    tar -C $Stage -czf $OutputPath .
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash
    "bundle=$OutputPath"
    "sha256=$hash"
}
finally {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
