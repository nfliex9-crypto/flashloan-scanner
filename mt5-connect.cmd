@echo off
setlocal EnableExtensions
title AEGIS MT5 Demo Read-Only Connector
echo.
echo AEGIS / MT5 DEMO / READ-ONLY
echo No broker password will be requested. Do not use a live trading account.
echo.
where py >nul 2>&1
if errorlevel 1 (
 echo Python launcher not found. Install 64-bit Python 3.12 from python.org.
 goto :failed
)
py -3.12 --version >nul 2>&1
if errorlevel 1 (
 echo Python 3.12 required. Install it from python.org and reopen this file.
 goto :failed
)
set "AEGIS_DIR=%LOCALAPPDATA%\AEGIS_MT5"
if not exist "%AEGIS_DIR%" mkdir "%AEGIS_DIR%"
echo Fetching the two publicly reviewable connector source files...
powershell.exe -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $base='https://raw.githubusercontent.com/nfliex9-crypto/flashloan-scanner/agent-city-v1/'; Invoke-WebRequest -Uri ($base+'mt5_bridge.py') -OutFile (Join-Path $env:AEGIS_DIR 'mt5_bridge.py') -UseBasicParsing; Invoke-WebRequest -Uri ($base+'aegis/demo_adapters.py') -OutFile (Join-Path $env:AEGIS_DIR 'demo_adapters.py') -UseBasicParsing;"
if errorlevel 1 (
 echo Unable to download the audited AEGIS connector source over HTTPS.
 goto :failed
)
echo Installing local dependencies. MT5 trading permissions remain disabled in AEGIS.
py -3.12 -m pip install --user --disable-pip-version-check MetaTrader5 keyring
if errorlevel 1 (
 echo Dependency installation failed. No trading orders were sent.
 goto :failed
)
echo.
echo Open MetaTrader 5 on your DEMO account, then enter the pairing code.
py -3.12 "%AEGIS_DIR%\mt5_bridge.py"
echo.
echo Connector exited. Your MT5 terminal remains untouched.
pause
exit /b 0
:failed
echo Setup stopped safely. Nothing was connected or traded.
pause
exit /b 1
