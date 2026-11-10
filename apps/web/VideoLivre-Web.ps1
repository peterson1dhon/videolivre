param(
    [ValidateSet('iniciar', 'parar', 'status')]
    [string]$Acao = 'iniciar',
    [switch]$SemNavegador
)

$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'target\release\videolivre-web.exe'
$data = if ($env:VLWEB_DATA) { $env:VLWEB_DATA } else { Join-Path $env:LOCALAPPDATA 'VideoLivreWeb' }
$port = if ($env:VLWEB_PORT) { [int]$env:VLWEB_PORT } else { 8787 }
if ($port -lt 1 -or $port -gt 65535) { throw 'Porta inválida.' }
$url = "http://localhost:$port"
$probe = "http://127.0.0.1:$port/api/v1/info"
$pidFile = Join-Path $data 'lancador.json'

$process = $null
if (Test-Path -LiteralPath $pidFile) {
    $record = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
    $candidate = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Path -eq $exe -and "$($candidate.StartTime.ToUniversalTime().Ticks)" -eq $record.started) {
        $process = $candidate
    }
}
if ($Acao -eq 'parar') {
    if ($process) { Stop-Process -Id $process.Id }
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile }
    return
}
if ($Acao -eq 'status') {
    if ($process) { Invoke-RestMethod $probe } else { 'VideoLivre Web está parado.' }
    return
}
if (!$process) {
    if (!(Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw 'Execute cargo build --locked --release dentro de apps/web.'
    }
    if (!$env:VLWEB_PYTHON -or !$env:VLWEB_PYTHON_PACKAGES) {
        $venv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        if (!(Test-Path -LiteralPath $venv -PathType Leaf)) { throw 'Prepare a .venv conforme o README.' }
        $details = & $venv -I -c 'import sys,sysconfig,json;print(json.dumps([sys._base_executable,sysconfig.get_path("purelib")]))'
        if ($LASTEXITCODE) { throw 'Não foi possível carregar o Python da .venv.' }
        $details = $details | ConvertFrom-Json
        $env:VLWEB_PYTHON = $details[0]
        $env:VLWEB_PYTHON_PACKAGES = $details[1]
    }
    if (!$env:VLWEB_FFMPEG) { $env:VLWEB_FFMPEG = (Get-Command ffmpeg.exe -CommandType Application).Source }
    $null = New-Item -ItemType Directory -Path $data -Force
    $process = Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot -PassThru -WindowStyle Hidden
    @{ pid = $process.Id; started = "$($process.StartTime.ToUniversalTime().Ticks)" } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $pidFile -Encoding utf8
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($process.HasExited) { break }
        try {
            $info = Invoke-RestMethod $probe -TimeoutSec 1
            if ($info.api -eq 'v1' -and !$process.HasExited) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 150 }
    }
    if (!$ready) { throw "Falha ao iniciar. Confira $data\erro-inicializacao.txt." }
}
if (!$SemNavegador) { Start-Process $url }
"VideoLivre Web em $url"
