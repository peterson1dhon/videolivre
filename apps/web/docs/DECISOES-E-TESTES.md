# Decisões e verificações

## Primeira versão

O fluxo começa pela fila em Rust, persiste mudanças de estado em JSON por substituição atômica e executa um item por vez. O motor mantido do yt-dlp descobre metadados e baixa em uma pasta por item. O FFmpeg combina trilhas ou converte o áudio. O servidor publica um arquivo regular em outra pasta do mesmo volume e a API entrega apenas o arquivo associado ao registro autenticado. Ao reiniciar após interrupção, os itens em execução voltam como cancelados e o usuário pode retomá-los. O Android pode funcionar de forma independente e integrar a API v1 quando fizer sentido.

## Modelo de segurança e limites

Rust reduz riscos de corrupção de memória no serviço. Validação, autenticação e isolamento exigem controles próprios. A porta do app escuta só em `127.0.0.1`; o acesso remoto previsto usa Tailscale Serve. A chave de 256 bits é gerada fora do repositório e a sessão usa identificadores aleatórios, cookie seguro e cabeçalho de mutação. O serviço tem um proprietário. Qualquer pessoa que receba a chave tem acesso à fila inteira.

O worker executa CPython isolado, sem processamento de `.pth`, com o pacote puro e fixado de yt-dlp. Somente o handler urllib é habilitado. Plugins, proxies, componentes remotos, runtimes JS e subprocessos do extrator ficam desabilitados. O handler valida a URL após cada redirecionamento. O hook de auditoria verifica o endereço numérico efetivamente passado ao socket, depois da resolução, e aceita apenas TCP em 80/443 para endereços públicos. Assim, DNS para IP privado, link-local, CGNAT, IPv6 mapeado ou loopback é barrado no ponto de conexão. O FFmpeg é chamado separadamente com argumentos fixos, entradas locais com nomes gerados, lista de demuxers de mídia e protocolos `file,pipe`. No Windows, Job Objects encerram subprocessos quando o servidor sai e limitam processos e memória.

Esses controles pressupõem dependências e arquivos locais confiáveis. O hook do CPython protege os caminhos de rede usados pelo worker e não é sandbox para Python ou extensões arbitrárias. Endereços globalmente roteáveis que a rede local redireciona a serviços privados ainda são um risco. Um host com roteamento incomum, serviços internos expostos em IPs públicos ou exigência de receber links de terceiros precisa de política de saída ou isolamento de rede adicional. Use a conta padrão do Windows e mantenha o FFmpeg, o CPython e o yt-dlp atualizados. Atualizar o pacote fixado exige repetir os testes do worker, pois o adaptador usa pontos internos do yt-dlp. Binários de mídia malformados continuam sendo entrada não confiável para o FFmpeg.

Limites padrão de 30 minutos por item, 512 MiB por área de trabalho, 10 GiB de armazenamento do serviço e 1 GiB de reserva livre no volume. Trilhas parciais e saída de conversão contam juntas. O monitor verifica espaço durante a execução, com uma pequena margem possível entre verificações. Cancelamento mantém parciais até retomada ou limpeza. A pasta de dados também contém URLs originais e pode conter links privados, assinados ou expirados. Restrinja o acesso à pasta e não compartilhe seu conteúdo em diagnósticos.

## Como reproduzir

No PowerShell, em `apps/web`, com a configuração do README:

```powershell
cargo test --locked
cargo build --locked --release
.\.venv\Scripts\python.exe tests\test_worker.py -v
```

Para o teste integrado, configure as três variáveis de ferramentas descritas no README e execute `python tests\e2e.py target\release\videolivre-web.exe`. Ele cria uma pasta de dados temporária, usa o [trailer público de Sintel, do Blender](https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4), e encerra a instância depois da execução. Requer acesso à internet.

Para a checagem visual automatizada, inicie uma instância de teste com uma pasta de dados vazia e isolada. Instale Playwright em um ambiente separado e execute `python tests\browser.py http://localhost:8787 <caminho-da-chave-de-teste>` no Windows com Edge instalado. O teste limpa o histórico dessa instância.

## Resultado no Windows

Em 9 de novembro de 2026, passaram os testes unitários de Rust e do worker Python, o build otimizado para Windows x64 (alvo GNU) e o teste integrado com MP4 e MP3 reais. O teste verificou autenticação, proteção da sessão, cancelamento e reenvio à fila, crédito com acentos, requisição Range, colisões de nomes, reinício e preservação dos arquivos ao limpar o histórico. Um teste à parte com um manifesto DASH do Shaka Player gerou um MKV com duas trilhas. O teste no Edge verificou login, formulário, download e limpeza em viewport móvel. A revisão complementar usou 320, 390 e 1280 px e verificou foco ao mudar a etapa do download.

A retomada foi verificada como reenvio à fila. A continuidade no byte exato depende da origem e não foi medida. A sintaxe do Tailscale Serve foi conferida na documentação oficial. A conexão pela tailnet, a instalação como PWA e o compartilhamento nativo ainda precisam de teste em aparelho físico.

O lançador PowerShell iniciou o executável em segundo plano, consultou a versão e encerrou a instância usando uma pasta de teste e uma porta separada.
