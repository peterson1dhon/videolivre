# VideoLivre

Gerenciador de downloads de vídeos de diferentes sites, com interface em português para **Windows**. Usa yt-dlp para os downloads e FFmpeg para combinar vídeo e áudio ou converter para MP3.

“Diferentes plataformas” refere-se aos sites de vídeo suportados pelo yt-dlp. Esta versão do aplicativo foi desenvolvida para Windows; não foi adaptada para Linux ou macOS.

## Recursos

- Colar o link de um vídeo e adicionar à fila.
- Melhor qualidade disponível ou limite de 1080p, 720p e 480p.
- Extração de áudio para MP3.
- Escolha da pasta de destino.
- Fila persistente com downloads sequenciais.
- Recuperação da última cópia válida da fila e retomada de itens interrompidos em estado pausado.
- Pausa e tentativa de retomada, quando suportadas pelo servidor.
- Progresso percentual e diagnóstico de erro por item.
- Quando o site fornece o perfil do criador, inclui o @ no nome do arquivo para facilitar os créditos.
- Limpar os itens concluídos sem apagar os arquivos.
- Abrir a pasta do download selecionado.

## Executar pelo código-fonte

Requisitos: Windows, Python 3.11 ou superior com Tkinter. Node.js no PATH é usado quando disponível para os extratores que precisam de JavaScript; algumas plataformas podem exigir configuração adicional.

No PowerShell, dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe preparar_ffmpeg.py
.\.venv\Scripts\python.exe app.py
```

O script de preparação copia o FFmpeg do pacote imageio-ffmpeg para a pasta do projeto. O executável e o ambiente Python não são versionados.

## Gerar o aplicativo Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

O resultado fica em `dist/VideoLivre/VideoLivre.exe`. Mantenha a pasta inteira, incluindo `_internal` e `ffmpeg.exe`, ao copiar o aplicativo para outro local. O pacote local não possui assinatura digital.

## Como usar

1. Cole o link do vídeo.
2. Escolha a qualidade e a pasta.
3. Clique em **Adicionar à fila**.
4. Selecione um item para pausar, retomar ou abrir a pasta.

**Limpar lista de baixados** remove somente os registros concluídos. Os arquivos permanecem no disco. Sem seleção, **Ir até a pasta do download** abre a pasta padrão.

A fila fica em `%LOCALAPPDATA%\VideoLivre\queue.json`. Ao reabrir o aplicativo, downloads pendentes ficam pausados. Arquivos parciais são mantidos para permitir retomada.

O VideoLivre conserva uma cópia da fila anterior em `%LOCALAPPDATA%\VideoLivre\queue.backup.json`. Se o arquivo principal estiver inválido, ele tenta recuperar a fila anterior e preserva uma cópia do arquivo danificado. Se um item falhar, selecione-o para usar **Ver erro** ou **Copiar diagnóstico**; revise o texto antes de compartilhá-lo.

## Limitações e verificações

- A compatibilidade depende do yt-dlp e pode mudar quando um site muda.
- Não inclui extensão de navegador, captura automática, downloads de playlists ou suporte a DRM.
- Login e restrições do site podem impedir downloads.
- Vídeo e áudio separados são combinados em MKV; arquivos já combinados podem manter seu formato original.
- A retomada pode repetir a etapa de conversão ou combinação.
- Foram verificados download de um vídeo de teste local, conversão para MP3, inicialização do executável e visibilidade dos botões em dois tamanhos de janela. Isso não garante funcionamento em todos os sites.

## Arquivos

| Arquivo | Função |
| --- | --- |
| `app.py` | Interface, fila e execução do yt-dlp |
| `requirements.txt` | Dependências de execução e preparação |
| `preparar_ffmpeg.py` | Prepara o FFmpeg local |
| `build.ps1` | Gera a distribuição Windows |
| `COMPONENTES.txt` | Componentes e referências de licenciamento |

Este projeto é independente do Internet Download Manager e não utiliza seu código ou sua marca. Os componentes de terceiros mantêm suas próprias licenças. Este repositório não define uma licença de redistribuição para o código da interface.

