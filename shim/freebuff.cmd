@echo off
rem Reindirizza freebuff al terminale web. Per il freebuff originale: set FREEBUFFT_DIRECT=1
python "%~dp0..\freebuffserver.py" open "%CD%" %*
