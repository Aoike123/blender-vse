# Blender VSE Control one-line installer for Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Aoike123/blender-vse/main/install.ps1 | iex"
#
# Installs uv when missing, then installs the `blender-vse-mcp` command with
# uv's managed Python 3.12. It never edits MCP host configuration; register the
# printed command in your host yourself.
#
# Overrides: BLENDER_VSE_SOURCE (pip-style source: git URL or local path),
#            BLENDER_VSE_REF (git ref, default main).
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Aoike123/blender-vse"
$Ref = if ($env:BLENDER_VSE_REF) { $env:BLENDER_VSE_REF } else { "main" }
$Source = if ($env:BLENDER_VSE_SOURCE) { $env:BLENDER_VSE_SOURCE } else { "git+$RepoUrl@$Ref" }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> uv not found; installing it from https://astral.sh/uv"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv was installed but is not on PATH; open a new terminal and rerun"
    }
}

Write-Host "==> Installing blender-vse-mcp from $Source"
uv tool install --force --python 3.12 "blender-vse-control[mcp] @ $Source"
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed" }

$BinDir = (uv tool dir --bin).Trim()
$McpBin = Join-Path $BinDir "blender-vse-mcp.exe"
if (-not (Test-Path $McpBin)) { throw "install finished but $McpBin is missing" }

$Blender = $env:BLENDER_VSE_BLENDER_EXECUTABLE
if (-not $Blender) {
    $cmd = Get-Command blender -ErrorAction SilentlyContinue
    if ($cmd) { $Blender = $cmd.Source }
}
if (-not $Blender) {
    $Blender = Get-ChildItem "$env:ProgramFiles\Blender Foundation\*\blender.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}

Write-Host ""
Write-Host "Installed: $McpBin"
if ($Blender) {
    Write-Host "Blender:   $Blender"
} else {
    Write-Host "Blender:   not found. Install Blender 4.2+ from https://www.blender.org/download/"
    Write-Host "           or set BLENDER_VSE_BLENDER_EXECUTABLE to its executable."
}
if (-not (($env:Path -split ";") -contains $BinDir)) {
    Write-Host "PATH:      add $BinDir to PATH, or use the full path above."
}
Write-Host ""
Write-Host "Register it as a stdio MCP server named blender-vse, command: blender-vse-mcp"
Write-Host "Projects are kept in <workspace>\blender-vse-projects of the folder the host runs in."
