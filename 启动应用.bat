@echo off
setlocal
cd /d "%~dp0"
if not defined FINSOCRATIC_HOME (
  if exist "D:\" (
    set "FINSOCRATIC_HOME=D:\FinSocratic-ResearchAgent"
  ) else (
    set "FINSOCRATIC_HOME=%LOCALAPPDATA%\FinSocratic-ResearchAgent"
  )
)
if not defined FINSOCRATIC_ENV set "FINSOCRATIC_ENV=%FINSOCRATIC_HOME%\runtime"
set "PIP_CACHE_DIR=%FINSOCRATIC_HOME%\cache\pip"
set "PYTHONPYCACHEPREFIX=%FINSOCRATIC_HOME%\cache\pycache"
set "npm_config_cache=%FINSOCRATIC_HOME%\cache\npm"
set "TEMP=%FINSOCRATIC_HOME%\temp"
set "TMP=%TEMP%"
if not exist "%FINSOCRATIC_HOME%\cache\pip" mkdir "%FINSOCRATIC_HOME%\cache\pip"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%FINSOCRATIC_HOME%\data" mkdir "%FINSOCRATIC_HOME%\data"
if not defined FINSOCRATIC_PYTHON (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "FINSOCRATIC_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  ) else (
    set "FINSOCRATIC_PYTHON=python"
  )
)
if not exist "%FINSOCRATIC_ENV%\Scripts\python.exe" (
  echo Creating local Python environment...
  "%FINSOCRATIC_PYTHON%" -c "import sys; sys.exit(not sys.version_info >= (3, 11))"
  if errorlevel 1 goto failed
  "%FINSOCRATIC_PYTHON%" -m venv --without-pip "%FINSOCRATIC_ENV%"
  if errorlevel 1 goto failed
)
"%FINSOCRATIC_ENV%\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo Bootstrapping pip in the local environment...
  "%FINSOCRATIC_PYTHON%" -m pip --python "%FINSOCRATIC_ENV%" install --upgrade pip
  if errorlevel 1 goto failed
)
echo Installing or updating application dependencies...
"%FINSOCRATIC_ENV%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Starting FinSocratic at http://localhost:8501
if not exist "frontend\dist\index.html" (
  echo Building React frontend...
  pushd frontend
  call npm ci
  if errorlevel 1 goto failed
  call npm run build
  if errorlevel 1 goto failed
  popd
)
"%FINSOCRATIC_ENV%\Scripts\python.exe" -m finsocratic.api
goto end
:failed
echo.
echo Startup failed. Install Python 3.11+ or set FINSOCRATIC_PYTHON to its executable path, and check the data drive has enough free space.
pause
:end
endlocal
