@echo off
chcp 65001 >nul
rem ==========================================================================
rem  养老政策一站通 · 局域网访问服务启动器
rem  双击运行同目录下的 server.py，让同一个 Wi-Fi / 热点下的手机也能打开网站
rem  停止服务：关掉这个命令行窗口，或按 Ctrl+C
rem ==========================================================================
setlocal
cd /d "%~dp0"

if not exist "%~dp0server.py" (
  echo.
  echo  [错误] 未找到 server.py，请确认它与本脚本在同一个文件夹。
  echo.
  pause
  exit /b 1
)

rem ---- 探测可用的 Python（跳过 Microsoft Store 的占位别名）----
set "PY="
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
  if not defined PY (
    echo %%P| findstr /i /c:"\\WindowsApps\\" >nul 2>nul
    if errorlevel 1 set "PY=%%P"
  )
)
if not defined PY for /f "delims=" %%P in ('where py.exe 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY goto :nopython

"%PY%" -c "import sys;raise SystemExit(0 if sys.version_info[0]==3 and sys.version_info[1] in range(8,20) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython

echo  正在启动局域网服务，请保持本窗口开着…
echo.
"%PY%" "%~dp0server.py"
echo.
echo  服务已停止。
pause
exit /b 0

:nopython
echo.
echo  ============================================================
echo   未检测到可用的 Python
echo   请先安装 Python 3.8+ 并勾选 Add to PATH
echo   下载地址：https://www.python.org/downloads/
echo  ============================================================
echo.
pause
exit /b 1
