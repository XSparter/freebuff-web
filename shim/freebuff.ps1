# Reindirizza freebuff al terminale web. Per il freebuff originale: $env:FREEBUFFT_DIRECT=1
python "$PSScriptRoot\..\freebuffserver.py" open "$PWD" @args
exit $LASTEXITCODE
