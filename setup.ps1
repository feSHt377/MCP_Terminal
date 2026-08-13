param(
    [switch]$RunGui
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        & py -3 -m venv (Join-Path $ProjectRoot ".venv")
    } else {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $PythonCommand) {
            throw "Python was not found. Install Python 3.10-3.14 and run setup.ps1 again."
        }
        & python -m venv (Join-Path $ProjectRoot ".venv")
    }
}

$PipMirror = "https://pypi.tuna.tsinghua.edu.cn/simple"
& $VenvPython -m pip install --upgrade pip -i $PipMirror
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt") -i $PipMirror
& $VenvPython -X utf8 (Join-Path $ProjectRoot "tests\test_core.py")

Write-Host ""
Write-Host "mcpterminal setup completed. VS Code MCP config: .vscode\mcp.json" -ForegroundColor Green

if ($RunGui) {
    & $VenvPython -m app.main
}
