param(
  [string]$DestinationRoot = "$env:USERPROFILE\.codex\skills"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$destinationRootResolved = [System.IO.Path]::GetFullPath($DestinationRoot)
$destinationPath = Join-Path $destinationRootResolved "code-autopsy"

New-Item -ItemType Directory -Force -Path $destinationRootResolved | Out-Null

if (Test-Path $destinationPath) {
  Write-Error "Destination already exists: $destinationPath`nRemove it first or pass a different destination root."
  exit 1
}

New-Item -ItemType Junction -Path $destinationPath -Target $skillRoot | Out-Null

Write-Output "Installed skill at: $destinationPath"
Write-Output "Restart Codex to pick up new skills."
