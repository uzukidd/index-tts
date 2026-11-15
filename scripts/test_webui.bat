@echo off
setlocal
pushd "%~dp0.."
if /I "%~1"=="--browser" (
  set "INDEXTTS_UI_TESTS=1"
  shift
)
conda run --no-capture-output -n indextts python -m pytest -q tests/test_webui_syntax.py tests/test_webui_handlers.py tests/test_webui_batch.py tests/test_webui_batch_ui.py
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
