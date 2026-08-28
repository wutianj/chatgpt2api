param(
  [string]$BundlePath = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $BundlePath) {
  $releaseDir = Join-Path $RepoRoot "output\release"
  $bundle = Get-ChildItem -LiteralPath $releaseDir -Filter "reg2-import-bundle-*.zip" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $bundle) {
    throw "no reg2-import-bundle zip found under $releaseDir"
  }
  $BundlePath = $bundle.FullName
}

$BundlePath = (Resolve-Path $BundlePath).Path
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($BundlePath)
try {
  $entryMap = @{}
  foreach ($entry in $archive.Entries) {
    $entryMap[$entry.FullName.Replace("\", "/")] = $entry.FullName
  }
  $entries = @($entryMap.Keys)
  $required = @(
    "README.md",
    "manifest.json",
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

  $missing = @($required | Where-Object { $entries -notcontains $_ })
  if ($missing.Count) {
    throw "bundle missing entries: $($missing -join ', ')"
  }

  function Read-ZipText {
    param([string]$Name)
    $resolvedName = $entryMap[$Name.Replace("\", "/")]
    if (-not $resolvedName) {
      throw "missing zip entry: $Name"
    }
    $entry = $archive.GetEntry($resolvedName)
    if (-not $entry) {
      throw "missing zip entry: $Name"
    }
    $reader = [IO.StreamReader]::new($entry.Open())
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
  }

  function Get-ZipEntryHash {
    param([string]$Name)
    $resolvedName = $entryMap[$Name.Replace("\", "/")]
    if (-not $resolvedName) {
      throw "missing zip entry: $Name"
    }
    $entry = $archive.GetEntry($resolvedName)
    if (-not $entry) {
      throw "missing zip entry: $Name"
    }
    $stream = $entry.Open()
    try {
      $sha = [System.Security.Cryptography.SHA256]::Create()
      try {
        return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace("-", "")
      }
      finally {
        $sha.Dispose()
      }
    }
    finally {
      $stream.Dispose()
    }
  }

  $accounts = Read-ZipText "api/accounts.py"
  $apply = Read-ZipText "apply-reg2-import-bundle.sh"
  $readme = Read-ZipText "README.md"
  $manifestText = Read-ZipText "manifest.json"
  $sample = Read-ZipText "docs/runbooks/examples/reg2-image-site-sample.jsonl"
  $smoke = Read-ZipText "scripts/smoke_reg2_import.py"
  $push = Read-ZipText "deploy/push-reg2-import-bundle.ps1"
  if (-not $accounts.Contains("/api/accounts/import/reg2")) {
    throw "api/accounts.py does not contain reg2 import route"
  }
  if (-not $apply.Contains("bundle web_dist does not contain reg2 import UI text")) {
    throw "apply script does not validate bundle frontend marker"
  }
  if (-not $apply.Contains("manifest ok")) {
    throw "apply script does not validate manifest hashes"
  }
  if (-not $apply.Contains('docker cp "${BUNDLE_DIR}/api/accounts.py"')) {
    throw "apply script does not sync backend code into the running container"
  }
  if (-not $apply.Contains('"${BACKUP_DIR}/container/accounts.py"')) {
    throw "apply script does not back up and roll back container backend code"
  }
  if (-not $apply.Contains('"${BACKUP_DIR}/container/web_dist"')) {
    throw "apply script does not back up and roll back container frontend code"
  }
  if (-not $apply.Contains("tar -C /app/web_dist")) {
    throw "apply script does not sync frontend code into the running container"
  }
  if (-not $apply.Contains("http://127.0.0.1:3000/openapi.json")) {
    throw "apply script does not validate the running service route"
  }
  if (-not $apply.Contains("sleep 2")) {
    throw "apply script does not wait for the service to become ready after restart"
  }
  if (-not $apply.Contains("docker commit")) {
    throw "apply script does not persist the patched container as an image"
  }
  if (-not $apply.Contains('install -m 644 "${BUNDLE_DIR}/CHANGELOG.md"')) {
    throw "apply script does not install CHANGELOG.md"
  }
  if (-not $apply.Contains('"${BACKUP_DIR}/CHANGELOG.md"')) {
    throw "apply script does not roll back CHANGELOG.md"
  }
  if (-not $apply.Contains("installed web_dist does not contain reg2 import UI text")) {
    throw "apply script does not validate installed frontend marker"
  }
  if (-not $readme.Contains("push-reg2-import-bundle.ps1")) {
    throw "README does not mention Windows push helper"
  }
  if (-not $readme.Contains("-DryRun")) {
    throw "README does not mention push dry-run"
  }
  if (-not $sample.Contains("sample-access-token-1")) {
    throw "sample jsonl does not contain expected fake token"
  }
  if (-not $smoke.Contains("/api/accounts/import/reg2")) {
    throw "smoke script does not call reg2 import route"
  }
  if (-not $push.Contains('reg2-import-bundle-$stamp.zip')) {
    throw "push script does not use a timestamped remote zip"
  }
  if (-not $push.Contains('verify-reg2-import-bundle.ps1')) {
    throw "push script does not verify the local bundle before upload"
  }
  if (-not $push.Contains("zip entry escapes target dir")) {
    throw "push script does not validate zip extraction paths"
  }
  $manifest = $manifestText | ConvertFrom-Json
  if ($manifest.name -ne "reg2-import-bundle") {
    throw "manifest name is invalid"
  }
  $manifestPaths = @($manifest.files | ForEach-Object { [string]$_.path })
  foreach ($requiredPath in $required | Where-Object { $_ -ne "manifest.json" }) {
    if ($manifestPaths -notcontains $requiredPath) {
      throw "manifest missing required path: $requiredPath"
    }
  }
  foreach ($file in @($manifest.files)) {
    $path = [string]$file.path
    $expectedHash = [string]$file.sha256
    if (-not $path -or -not $expectedHash) {
      throw "manifest contains an invalid file entry"
    }
    $actualHash = Get-ZipEntryHash $path
    if ($actualHash -ne $expectedHash.ToUpperInvariant()) {
      throw "manifest hash mismatch for ${path}: $actualHash != $expectedHash"
    }
  }

  $frontendAssets = @($entries | Where-Object {
    $_.StartsWith("web_dist/assets/") -and $_.EndsWith(".js")
  })
  $frontendUiMatches = @($frontendAssets | Where-Object {
    (Read-ZipText $_).Contains("reg2_jsonl")
  })
  $frontendApiMatches = @($frontendAssets | Where-Object {
    (Read-ZipText $_).Contains("/api/accounts/import/reg2")
  })
  $frontendDropPanelMatches = @($frontendAssets | Where-Object {
    (Read-ZipText $_).Contains("account-file-import-panel")
  })
  $frontendNativeInputMatches = @($frontendAssets | Where-Object {
    (Read-ZipText $_).Contains("account-file-dropzone__button")
  })
  if (-not $frontendUiMatches.Count) {
    throw "web_dist assets do not contain reg2 import mode marker"
  }
  if (-not $frontendApiMatches.Count) {
    throw "web_dist assets do not contain reg2 import API marker"
  }
  if (-not $frontendDropPanelMatches.Count) {
    throw "web_dist assets do not contain reg2 drag-drop panel marker"
  }
  if (-not $frontendNativeInputMatches.Count) {
    throw "web_dist assets do not contain native reg2 file input marker"
  }

  $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $BundlePath
  [pscustomobject]@{
    Bundle = $BundlePath
    Length = (Get-Item -LiteralPath $BundlePath).Length
    SHA256 = $hash.Hash
    RequiredEntries = $required.Count
    FrontendUiMarkerFiles = $frontendUiMatches.Count
    FrontendApiMarkerFiles = $frontendApiMatches.Count
    FrontendDropPanelFiles = $frontendDropPanelMatches.Count
    FrontendNativeInputFiles = $frontendNativeInputMatches.Count
    Status = "ok"
  }
}
finally {
  $archive.Dispose()
}
