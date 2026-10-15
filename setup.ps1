param(
    [switch]$RunGui,
    [switch]$RunTests,
    [string]$PipMirror = 'https://pypi.tuna.tsinghua.edu.cn/simple',
    [switch]$RecreateVenv
)

$ErrorActionPreference = 'Stop'

# Force Python UTF-8 mode globally to prevent Windows CP936/GBK UnicodeDecodeError
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# 1. Lock working directory to project root
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

Write-Host "=== MCP Terminal Setup ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"

# 2. Find valid Python (3.10 - 3.14)
function Test-PythonCandidate {
    param(
        [string]$cmdPath,
        [string[]]$extraArgs = @()
    )
    try {
        $checkScript = "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))"
        $allArgs = @()
        if ($extraArgs) {
            $allArgs += $extraArgs
        }
        $allArgs += @('-c', $checkScript)

        $output = & $cmdPath $allArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            $ver = ($output -join '').Trim()
            if ($ver -match '^3\.(1[0-4])$') {
                return @{ Path = $cmdPath; Args = $extraArgs; Version = $ver }
            }
        }
    } catch {}
    return $null
}

function Find-ValidPython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($v in @('-3.13', '-3.12', '-3.11', '-3.10', '-3.14', '-3')) {
            $c = Test-PythonCandidate -cmdPath $pyLauncher.Source -extraArgs @($v)
            if ($c) { return $c }
        }
    }

    $pythonCmds = Get-Command python -All -ErrorAction SilentlyContinue
    foreach ($p in $pythonCmds) {
        if ($p.Source -match 'WindowsApps') { continue }
        $c = Test-PythonCandidate -cmdPath $p.Source
        if ($c) { return $c }
    }

    return $null
}

$VenvDir = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

# 3. Check virtual environment health
$NeedCreateVenv = $RecreateVenv -or (-not (Test-Path -LiteralPath $VenvPython))
if (-not $NeedCreateVenv) {
    $venvCheck = Test-PythonCandidate -cmdPath $VenvPython
    if (-not $venvCheck) {
        Write-Warning "Existing virtual environment at '$VenvDir' is corrupted. Rebuilding..."
        $NeedCreateVenv = $true
    }
}

if ($NeedCreateVenv) {
    Write-Host "Searching for valid Python (3.10 - 3.14)..."
    $basePython = Find-ValidPython
    if (-not $basePython) {
        throw "No valid Python 3.10 - 3.14 found. Please install Python from python.org."
    }
    Write-Host ("Using Python " + $basePython.Version + ": " + $basePython.Path) -ForegroundColor Green

    if (Test-Path -LiteralPath $VenvDir) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Creating virtual environment at '$VenvDir'..."
    $createArgs = @()
    if ($basePython.Args) { $createArgs += $basePython.Args }
    $createArgs += @('-m', 'venv', $VenvDir)
    & $basePython.Path $createArgs
    if ($LASTEXITCODE -ne 0 -or (-not (Test-Path -LiteralPath $VenvPython))) {
        throw "Failed to create virtual environment."
    }
}

# 4. Install dependencies
$PipArgs = @('--timeout', '15', '--retries', '2')
if ($PipMirror) {
    $PipArgs += @('-i', $PipMirror)
}

Write-Host "Installing/verifying dependencies..." -ForegroundColor Cyan
& $VenvPython -X utf8 -m pip install @PipArgs -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0 -and $PipMirror) {
    Write-Warning "Installation with mirror failed. Falling back to default PyPI index..."
    & $VenvPython -X utf8 -m pip install --timeout 30 --retries 2 -r (Join-Path $ProjectRoot 'requirements.txt')
}

if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

# 5. Fast smoke verification
Write-Host "Verifying core dependencies..."
$verifyScript = "import PySide6; import asyncssh; import mcp; import yaml; import app.main; print('All core modules imported successfully.')"
& $VenvPython -X utf8 -c $verifyScript
if ($LASTEXITCODE -ne 0) {
    throw "Core module import verification failed."
}

# 6. Optional full test suite
if ($RunTests) {
    Write-Host "Running project core tests..." -ForegroundColor Cyan
    $testCore = Join-Path $ProjectRoot 'tests\test_core.py'
    & $VenvPython -X utf8 $testCore
    $uiSmoke = Join-Path $ProjectRoot 'tests\test_ui_smoke.py'
    if (Test-Path -LiteralPath $uiSmoke) {
        Write-Host "Running UI smoke tests..." -ForegroundColor Cyan
        & $VenvPython -X utf8 $uiSmoke
    }
}

# 7. Configure VS Code and Codex MCP paths
$vscodeDir = Join-Path $ProjectRoot '.vscode'
if (-not (Test-Path -LiteralPath $vscodeDir)) {
    New-Item -ItemType Directory -Path $vscodeDir | Out-Null
}
$vscodeMcpPath = Join-Path $vscodeDir 'mcp.json'
$vscodeMcpContent = @'
{
  "servers": {
    "mcpterminal": {
      "type": "stdio",
      "command": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.main", "--mcp"]
    }
  }
}
'@
Set-Content -LiteralPath $vscodeMcpPath -Value $vscodeMcpContent -Encoding utf8

$codexDir = Join-Path $ProjectRoot '.codex'
if (-not (Test-Path -LiteralPath $codexDir)) {
    New-Item -ItemType Directory -Path $codexDir | Out-Null
}
$codexTomlPath = Join-Path $codexDir 'config.toml'
$escPython = $VenvPython.Replace('\', '\\')
$escRoot = $ProjectRoot.Replace('\', '\\')
$codexTomlContent = "[mcp_servers.mcpterminal]`r`ncommand = `"$escPython`"`r`nargs = [`"-m`", `"app.main`", `"--mcp`"]`r`ncwd = `"$escRoot`"`r`n`r`n[mcp_servers.mcpterminal.env]`r`nPYTHONPATH = `"$escRoot`"`r`n"
Set-Content -LiteralPath $codexTomlPath -Value $codexTomlContent -Encoding utf8

Write-Host ""
Write-Host "mcpterminal setup completed successfully!" -ForegroundColor Green
Write-Host "  - VS Code MCP config: .vscode\mcp.json"
Write-Host "  - Codex MCP config:   .codex\config.toml"

if ($RunGui) {
    Write-Host "Starting GUI..."
    & $VenvPython -m app.main
}
