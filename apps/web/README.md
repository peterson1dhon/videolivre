# VideoLivre Web 0.1.0

Fila pessoal de downloads em português. O Windows executa o yt-dlp e o FFmpeg, guarda os arquivos e mantém a fila mesmo com a página fechada. No celular ou PC, abra a fila e use **Baixar arquivo** para copiar um resultado para o aparelho atual. A versão do servidor aparece no cabeçalho e em `/api/v1/info`.

## Executar no Windows

Use um usuário padrão e uma pasta privada em um volume NTFS local. É preciso ter [Rust estável com as ferramentas de compilação do Windows](https://rustup.rs/), [CPython 3.11 ou superior](https://www.python.org/downloads/windows/) e um [FFmpeg](https://ffmpeg.org/download.html) com codificador `libmp3lame`. O servidor usa as ferramentas instaladas no PC.

Dentro de `apps/web`, abra o PowerShell e execute:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt
cargo build --locked --release
.\VideoLivre-Web.ps1
```

Se o FFmpeg estiver fora do PATH, atribua o caminho completo antes de iniciar. Por exemplo, use `$env:VLWEB_FFMPEG = 'C:\Ferramentas\FFmpeg\bin\ffmpeg.exe'`. O lançador abre `http://localhost:8787` e roda o processo em segundo plano, sem registrar serviço ou tarefa automática. Use `.\VideoLivre-Web.ps1 -Acao status` para consultar e `.\VideoLivre-Web.ps1 -Acao parar` para encerrar. Em caso de falha de inicialização, consulte `%LOCALAPPDATA%\VideoLivreWeb\erro-inicializacao.txt`.

No primeiro uso, abra `%LOCALAPPDATA%\VideoLivreWeb\chave.txt` no PC e cole a chave na tela de entrada. Guarde-a como uma senha, inclusive ao transferi-la ao celular. Para trocar a chave, pare o serviço, mova a chave anterior e inicie novamente. As sessões expiram em 12 horas ou quando o serviço reinicia. A chave dá acesso a toda a fila e aos arquivos listados.

Use `VLWEB_DATA` para escolher outra pasta absoluta e privada e `VLWEB_PORT` para mudar a porta padrão de `8787`. Para iniciar o executável diretamente, configure também `VLWEB_FFMPEG`, `VLWEB_PYTHON` (executável base do CPython, sem usar o redirecionador da venv) e `VLWEB_PYTHON_PACKAGES` (caminho absoluto até `.venv\Lib\site-packages`). Mantenha esse ambiente dedicado ao yt-dlp.

## Acessar pelo celular com Tailscale

1. Instale o Tailscale no PC e no celular e entre na mesma tailnet. Restrinja a política de acesso da tailnet aos dispositivos que devem poder alcançar o PC.
2. Com o VideoLivre Web em execução, rode no PC o comando abaixo. Se o Tailscale oferecer a configuração de HTTPS da tailnet, siga o link oficial apresentado pelo cliente.
3. No celular, com o Tailscale ligado, abra o endereço HTTPS `*.ts.net` mostrado pelo comando. Entre com a chave do VideoLivre e teste **Baixar arquivo**. Com o Tailscale desligado no celular, o endereço deve ficar inacessível.

```powershell
tailscale serve --bg http://127.0.0.1:8787
tailscale serve status
# Para retirar apenas esse encaminhamento HTTPS, na porta padrão:
tailscale serve --bg http://127.0.0.1:8787 off
```

O Serve encaminha HTTPS só dentro da tailnet. Use **Serve**, mantenha o roteador sem redirecionamento para o app e deixe o PC ligado e conectado. A configuração de HTTPS pode registrar o nome DNS da máquina em logs públicos de certificados. A sintaxe foi conferida na documentação oficial. [Referência do Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) · [HTTPS e nomes de máquinas](https://tailscale.com/docs/how-to/set-up-https-certificates)

## Uso e arquivos

- Cole um link público individual e escolha a melhor qualidade, um limite de 1080p, 720p ou 480p, ou MP3. O título e o crédito detectado aparecem quando o extrator fornece metadados. O crédito manual aceita espaços, acentos e `@`, tem prioridade e o formulário o limpa após adicionar.
- Cancele um item em andamento ou na fila e use **Retomar**. A etapa interrompida pode reiniciar se o site não oferecer retomada, se o formato mudar ou se o trabalho já estiver no FFmpeg.
- O arquivo fica em `%LOCALAPPDATA%\VideoLivreWeb\downloads\<id-do-item>\` com nome como `Título [@criador].mp4`. Sem crédito confiável, fica só o título. Cada item tem uma pasta própria para preservar arquivos com nomes iguais. Um vídeo já combinado mantém seu formato. Trilhas separadas são combinadas em MKV.
- **Limpar histórico** retira os registros concluídos, cancelados e com erro. Os arquivos finalizados permanecem na pasta do PC. Itens ativos permanecem na fila. Para recuperar espaço dos arquivos finalizados, mova-os ou apague-os pelo Explorador do Windows.
- **Compartilhar link** usa o menu nativo de compartilhamento, quando disponível, para enviar o link original. Em navegadores compatíveis, instale a Web pelo menu ou adicione um atalho à tela inicial. O acesso ao servidor e a transferência para o aparelho exigem conexão.

## Escopo e componentes

Alguns sites exigem login, impersonação, um runtime JavaScript ou um downloader externo. Esta edição aceita somente os caminhos de extração e download nativo descritos nas [decisões e verificações](docs/DECISOES-E-TESTES.md). Playlists, transmissões ao vivo e DRM ficam fora do escopo. Baixe somente conteúdo que você tem permissão para salvar.

- **Rust/Axum/Tokio** cuidam do serviço e da fila. As versões transitivas estão em `Cargo.lock`. Axum e Tokio usam licença MIT. Consulte as licenças dos demais crates nas respectivas distribuições.
- **yt-dlp** é instalado via pacote Python puro, com a versão em `requirements.txt`. O código-fonte é distribuído sob Unlicense e inclui componentes de terceiros sob suas respectivas licenças. [Repositório do yt-dlp](https://github.com/yt-dlp/yt-dlp#license)
- **FFmpeg** é instalado separadamente. A licença do executável depende da compilação e pode ser LGPL ou GPL. [Informações legais do FFmpeg](https://ffmpeg.org/legal.html)

[API v1 para integração](docs/API.md) · [Decisões, riscos e testes](docs/DECISOES-E-TESTES.md)
