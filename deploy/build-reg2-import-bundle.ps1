param(
  [string]$OutputDir = "",
  [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputDir) {
  $OutputDir = Join-Path $RepoRoot "output\release"
}
$OutputDir = (New-Item -ItemType Directory -Path $OutputDir -Force).FullName

if (-not $SkipFrontendBuild) {
  Push-Location (Join-Path $RepoRoot "web-vue")
  try {
    npm run build --silent
  }
  finally {
    Pop-Location
  }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stage = Join-Path $OutputDir "reg2-import-bundle-$stamp"
$zip = "$stage.zip"

New-Item -ItemType Directory -Path (Join-Path $stage "api") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "web_dist") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "docs\runbooks") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "docs\runbooks\examples") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "deploy") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "scripts") -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $RepoRoot "api\accounts.py") -Destination (Join-Path $stage "api\accounts.py") -Force
Copy-Item -Path (Join-Path $RepoRoot "web-vue\dist\*") -Destination (Join-Path $stage "web_dist") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\runbooks\reg2-account-import.md") -Destination (Join-Path $stage "docs\runbooks\reg2-account-import.md") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\runbooks\examples\reg2-image-site-sample.jsonl") -Destination (Join-Path $stage "docs\runbooks\examples\reg2-image-site-sample.jsonl") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "scripts\smoke_reg2_import.py") -Destination (Join-Path $stage "scripts\smoke_reg2_import.py") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\apply-reg2-import-bundle.sh") -Destination (Join-Path $stage "apply-reg2-import-bundle.sh") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\apply-reg2-import-bundle.sh") -Destination (Join-Path $stage "deploy\apply-reg2-import-bundle.sh") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\push-reg2-import-bundle.ps1") -Destination (Join-Path $stage "deploy\push-reg2-import-bundle.ps1") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\verify-reg2-import-bundle.ps1") -Destination (Join-Path $stage "deploy\verify-reg2-import-bundle.ps1") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\build-reg2-import-bundle.ps1") -Destination (Join-Path $stage "deploy\build-reg2-import-bundle.ps1") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\REG2_IMPORT_BUNDLE_README.md") -Destination (Join-Path $stage "README.md") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "CHANGELOG.md") -Destination (Join-Path $stage "CHANGELOG.md") -Force

$manifestFiles = @(
  "README.md",
  "CHANGELOG.md",
  "api/accounts.py",
  "apply-reg2-import-bundle.sh",
  "deploy/apply-reg2-import-bundle.sh",
  "deploy/build-reg2-import-bundle.ps1",
  "deploy/push-reg2-import-bundle.ps1",
  "deploy/verify-reg2-import-bundle.ps1",
  "docs/runbooks/examples/reg2-image-site-sample.jsonl",
  "docs/runbooks/reg2-account-import.md",
  "scripts/smoke_reg2_import.py",
  "web_dist/index.html"
)
$manifestItems = foreach ($relativePath in $manifestFiles) {
  $fullPath = Join-Path $stage $relativePath
  $item = Get-Item -LiteralPath $fullPath
  [ordered]@{
    path = $relativePath.Replace("\", "/")
    bytes = $item.Length
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fullPath).Hash
  }
}
$manifest = [ordered]@{
  name = "reg2-import-bundle"
  created_at = (Get-Date).ToUniversalTime().ToString("o")
  source_version = (Get-Content -LiteralPath (Join-Path $RepoRoot "VERSION") -Raw).Trim()
  files = @($manifestItems)
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stage "manifest.json") -Encoding UTF8

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force

& (Join-Path $RepoRoot "deploy\verify-reg2-import-bundle.ps1") -BundlePath $zip
