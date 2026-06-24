@echo off
setlocal
cd /d %~dp0
echo Redirecting to ????.cmd
call "%~dp0????.cmd"
