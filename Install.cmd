@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Force Python UTF-8 mode to prevent Windows CP936/GBK UnicodeDecodeError
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM Disable QuickEdit mode to prevent accidental terminal freeze
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Console]::TreatControlCAsInput = $false; try { $h = [System.IntPtr]::Zero; $m = 0; $k = Add-Type -MemberDefinition '[DllImport(\"kernel32.dll\")] public static extern IntPtr GetStdHandle(int n); [DllImport(\"kernel32.dll\")] public static extern bool GetConsoleMode(IntPtr h, out uint m); [DllImport(\"kernel32.dll\")] public static extern bool SetConsoleMode(IntPtr h, uint m);' -Name 'CK' -Namespace 'C' -PassThru; $sh = $k::GetStdHandle(-10); if ($k::GetConsoleMode($sh, [ref]$m)) { $k::SetConsoleMode($sh, $m -band (-bnot 0x0040)) } } catch {}" >nul 2>&1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed. See the details above.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Installation completed successfully.
pause
