param(
  [Parameter(Mandatory = $true)]
  [string]$HostName,

  [string]$User = "root",
  [int]$Port = 22,
  [string]$IdentityFile = "",
  [string]$BundlePath = "",
  [string]$RemoteRoot = "/tmp",
  [string]$AppDir = "/opt/chatgpt2api",
  [string]$ContainerName = "chatgpt2api",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Require-Command {
  param([string]$Name)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "missing required command: $Name"
  }
}

Require-Command ssh
Require-Command scp

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
$verifyScript = Join-Path $PSScriptRoot "verify-reg2-import-bundle.ps1"
if (-not (Test-Path -LiteralPath $verifyScript)) {
  throw "missing verifier: $verifyScript"
}
& $verifyScript -BundlePath $BundlePath
if (-not $?) {
  throw "bundle verification failed"
}

$target = "${User}@${HostName}"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$RemoteDir = "$RemoteRoot/reg2-import-bundle-$stamp"
$remoteZip = "$RemoteRoot/reg2-import-bundle-$stamp.zip"
$sshBase = @("-p", "$Port")
$scpBase = @("-P", "$Port")
if ($IdentityFile) {
  $IdentityFile = (Resolve-Path $IdentityFile).Path
  $sshBase += @("-i", $IdentityFile)
  $scpBase += @("-i", $IdentityFile)
}

$remoteCommand = @"
set -euo pipefail
rm -rf '$RemoteDir'
mkdir -p '$RemoteDir'
python3 - '$remoteZip' '$RemoteDir' <<'PY'
import pathlib
import sys
import zipfile

zip_path = pathlib.Path(sys.argv[1]).resolve()
remote_dir = pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(zip_path) as archive:
    for member in archive.infolist():
        safe_name = member.filename.replace('\\', '/')
        target = (remote_dir / safe_name).resolve()
        if target != remote_dir and not str(target).startswith(str(remote_dir) + '/'):
            raise SystemExit(f'zip entry escapes target dir: {member.filename}')
        if member.is_dir() or safe_name.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open('wb') as output:
            output.write(source.read())
PY
cd '$RemoteDir'
APP_DIR='$AppDir' CONTAINER_NAME='$ContainerName' bash apply-reg2-import-bundle.sh
"@

Write-Host "bundle: $BundlePath"
Write-Host "target: $target"
Write-Host "remote dir: $RemoteDir"
if ($DryRun) {
  Write-Host "dry run: scp/ssh not executed"
  Write-Host "remote command:"
  Write-Host $remoteCommand
  exit 0
}

& scp @scpBase $BundlePath "${target}:${remoteZip}"
if ($LASTEXITCODE -ne 0) {
  throw "scp failed with exit code $LASTEXITCODE"
}

& ssh @sshBase $target $remoteCommand
if ($LASTEXITCODE -ne 0) {
  throw "remote apply failed with exit code $LASTEXITCODE"
}
