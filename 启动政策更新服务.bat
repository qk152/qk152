@echo off
setlocal
cd /d "%~dp0"

rem ==========================================================================
rem  养老政策站 · 启动脚本
rem  1) 自动探测可用的 Python 3.8+（自动排除 Microsoft Store 的占位别名）
rem  2) 用 pythonw.exe / pyw.exe 无窗口后台启动 crawler_server.py
rem  3) 浏览器由 crawler_server.py 自己打开，本脚本不重复打开
rem  4) 未检测到 Python 时弹窗提示“请先安装 Python 3.8+，并勾选 Add to PATH”
rem ==========================================================================

if not exist "%~dp0crawler_server.py" (
  echo.
  echo  [错误] 未找到 crawler_server.py，请确认本脚本与它放在同一个文件夹。
  echo.
  pause
  exit /b 1
)

set "RUN="
call :probe_python python.exe "" pythonw.exe
if not defined RUN call :probe_python py.exe "-3" "pyw.exe -3"
if not defined RUN goto :nopython

rem ---- 服务已在运行？直接打开网页即可 ----
call :probe_port
if not errorlevel 1 goto :already

rem ---- 无窗口后台启动服务 ----
start "养老政策站" /min %RUN% "%~dp0crawler_server.py"

rem ---- 最多等待约 10 秒，确认端口已监听 ----
set /a TRY=0
:wait
call :probe_port
if not errorlevel 1 goto :running
set /a TRY+=1
if %TRY% GEQ 20 goto :failed
ping -n 2 127.0.0.1 >nul
goto :wait

:running
rem 浏览器由 crawler_server.py 打开，这里不再重复打开
exit /b 0

:already
echo  [提示] 服务已在运行，正在打开网页……
start "" "%~dp0index.html"
exit /b 0

:failed
echo.
echo  [警告] 服务未能在预期时间内启动，改为以“离线模式”直接打开网页。
echo         网页仍可正常浏览内嵌的政策数据。
echo.
start "" "%~dp0index.html"
exit /b 0

rem --------------------------------------------------------------------------
rem  探测真实可用的 Python：先按 PATH 查找并排除 WindowsApps 占位别名，
rem  再用解释器自身做一次版本自检（要求 3.8+）
rem  %1=命令名    %2=附加参数    %3=无窗口启动命令
rem --------------------------------------------------------------------------
:probe_python
set "CAND="
for /f "delims=" %%P in ('where %~1 2^>nul') do (
  if not defined CAND (
    echo %%P| findstr /i /c:"\\WindowsApps\\" >nul 2>nul
    if errorlevel 1 set "CAND=%%P"
  )
)
if not defined CAND exit /b 0
"%~1" %~2 -c "import sys;raise SystemExit(0 if sys.version_info[0]==3 and sys.version_info[1] in range(8,20) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "RUN=%~3"
exit /b 0

rem ---- 检测 127.0.0.1:8765 是否已监听 ----
:probe_port
netstat -ano | findstr /c:"LISTENING" | findstr /c:"127.0.0.1:8765" >nul 2>nul
exit /b %errorlevel%

:nopython
echo.
echo  ==========================================================
echo   [错误] 未检测到可用的 Python 3.8+
echo.
echo   请先安装 Python 3.8+，并勾选 Add to PATH
echo   下载地址：https://www.python.org/downloads/
echo  ==========================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show('请先安装 Python 3.8+，并勾选 Add to PATH','养老政策站','OK','Warning')" >nul 2>nul
start "" "https://www.python.org/downloads/"
pause
exit /b 1
