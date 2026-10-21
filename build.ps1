$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python.' }
    }
    $pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    & $pythonExe -m pip install -r requirements.txt 'pyinstaller==6.22.3'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências.' }
    & $pythonExe preparar_ffmpeg.py
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar FFmpeg.' }
    & $pythonExe -m PyInstaller --noconfirm --onedir --console --name VideoLivre --collect-all yt_dlp --collect-all yt_dlp_ejs app.py
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar executável.' }
    Copy-Item ffmpeg.exe dist\VideoLivre\ffmpeg.exe -Force
    Copy-Item README.md,COMPONENTES.txt dist\VideoLivre -Force
    Write-Output 'Aplicativo pronto em dist\VideoLivre\VideoLivre.exe'
} finally {
    Pop-Location
}
