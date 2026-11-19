@echo off
rem Double-click to start ScrapTrust (web app + API + Copilot) and open it in your browser.
title ScrapTrust
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_scraptrust.ps1" %*
if errorlevel 1 pause
