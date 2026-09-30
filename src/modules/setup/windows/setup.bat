@echo off
:: This automatically asks Windows for Admin rights
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Running Touch2Key Setup...
    touch2key-setup
    pause
) else (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
)
