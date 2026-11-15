@echo off
setlocal
set "NO_PROXY=localhost,127.0.0.1"
pushd "%~dp0.."
conda run --no-capture-output -n indextts python webui.py --ui-only --host 127.0.0.1 --port 7861 %*
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
