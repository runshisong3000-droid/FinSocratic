$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$dataRoot = 'D:\FinSocratic-ResearchAgent'
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8501/api/health' -TimeoutSec 3
    if ($health.status -eq 'ok') { Start-Process 'http://127.0.0.1:8501/'; exit }
} catch {}
New-Item -ItemType Directory -Force -Path "$dataRoot\logs" | Out-Null
$env:PYTHONPYCACHEPREFIX = "$dataRoot\cache\pycache"
$env:TEMP = "$dataRoot\temp"
$env:TMP = $env:TEMP
Start-Process -FilePath "$dataRoot\runtime\Scripts\python.exe" -ArgumentList '-m','finsocratic.api' -WorkingDirectory $appRoot -WindowStyle Hidden -RedirectStandardOutput "$dataRoot\logs\server-out.log" -RedirectStandardError "$dataRoot\logs\server-error.log"
for ($attempt=0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8501/api/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { Start-Process 'http://127.0.0.1:8501/'; exit }
    } catch {}
}
throw "服务启动失败，请查看 $dataRoot\logs\server-error.log"
