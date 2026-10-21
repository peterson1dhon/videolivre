# Plano de melhorias do VideoLivre

Este documento é uma proposta de trabalho para outro GPT ou desenvolvedor. As tarefas abaixo **ainda não foram implementadas por este plano**. Marque uma tarefa somente depois de implementá-la e verificar seus critérios de conclusão.

Repositório: https://github.com/peterson1dhon/videolivre

## Contexto e cuidados para quem continuar

O VideoLivre é um aplicativo desktop para Windows, escrito em Python e Tkinter. Usa yt-dlp em um processo separado e FFmpeg para combinar vídeo e áudio ou converter para MP3. Suporte a vários sites não significa suporte atual a vários sistemas operacionais.

A base analisada tem a interface, a fila e o processamento em `app.py`; `command()` monta o comando, `worker()` executa o processo, `tick()` recebe seus eventos e `save()` grava a fila. A fila fica em `%LOCALAPPDATA%\\VideoLivre\\queue.json`. Consulte a versão mais recente do repositório antes de editar.

Já existem: pausa, retomada, remoção de itens, escolha de pasta, limpeza dos concluídos e abertura da pasta. Melhore esses recursos em vez de criar botões duplicados. Limpar histórico deve preservar os arquivos baixados.

Mantenha a interface em português e o aplicativo utilizável durante consultas e downloads. Atualizações do Tkinter devem ocorrer na thread principal. Preserve a execução pelo código-fonte e pelo executável empacotado. Evite reescrever o aplicativo ou trocar sua tecnologia sem uma necessidade demonstrada.

## Ordem sugerida

| Etapa | Tarefas | Objetivo |
| --- | --- | --- |
| 1 — Confiabilidade | 01 a 04 | Proteger a fila e explicar falhas |
| 2 — Uso diário | 05 a 08 | Facilitar downloads e localização dos arquivos |
| 3 — Organização | 09 e 10 | Melhorar leitura e controle da fila |
| 4 — Distribuição | 11 e 12 | Facilitar instalação e manutenção |
| Futuro opcional | 13 e 14 | Playlists e outros sistemas |

Faça uma tarefa por vez e registre o resultado antes de começar a próxima. As verificações abaixo são critérios propostos para a implementação futura; não são resultados de testes já executados.

## Etapa 1 — Confiabilidade

### [ ] 01. Proteger e recuperar o histórico

**Para quê:** evitar que um arquivo de fila danificado impeça a abertura ou faça o histórico desaparecer silenciosamente.

**Situação atual:** existe gravação por arquivo temporário e substituição, mas os itens carregados não têm validação completa. Falhas de escrita não recebem tratamento amigável.

**Implementar:**
- Validar a estrutura de cada item, identificadores únicos, URL, pasta, qualidade e estado.
- Introduzir uma versão do formato e migrar o arquivo antigo sem perder os downloads.
- Manter uma cópia recuperável da última fila válida; preservar o arquivo danificado para recuperação.
- Mostrar um aviso claro se não houver permissão ou espaço para salvar.
- Separar o estado interno do texto exibido: por exemplo, `downloading` e um campo numérico de progresso, em vez de depender de textos como “Baixando 45%”.

**Pronto quando:** fila antiga, arquivo vazio, JSON inválido, item incompleto e falha de gravação recebem tratamento previsível; a janela abre; a recuperação não apaga arquivos baixados. Itens interrompidos voltam pausados.

### [ ] 02. Conferir dependências e pasta de destino

**Para quê:** mostrar o que falta antes de começar um download que não poderá terminar.

**Implementar:**
- Conferir yt-dlp e FFmpeg; informar a versão do aplicativo e dos componentes.
- Detectar Node.js e explicar quando sua ausência pode afetar um site, sem bloquear todos os downloads.
- Validar escrita na pasta e informar espaço livre. Só comparar com o tamanho necessário quando houver uma estimativa confiável.
- Oferecer instruções de correção compatíveis com execução por Python e com o aplicativo empacotado.

**Pronto quando:** ausência de FFmpeg, pasta removida e pasta sem permissão geram mensagens compreensíveis; uma pasta válida permite continuar. Nenhum componente é instalado silenciosamente.

### [ ] 03. Mostrar erros úteis por download

**Para quê:** permitir que o usuário entenda por que um item falhou e como agir.

**Situação atual:** o painel de texto é compartilhado e limitado; um download novo pode substituir o contexto de uma falha anterior.

**Implementar:**
- Guardar um resumo e detalhes limitados por item.
- Diferenciar, quando houver evidência: problema de conexão, vídeo indisponível, autenticação exigida, formato indisponível, erro do FFmpeg e erro de gravação.
- Oferecer “Ver detalhes” e “Copiar diagnóstico”, com versões dos componentes.
- Remover tokens, credenciais e parâmetros sensíveis dos diagnósticos compartilháveis; permitir revisar o texto antes de exportar.
- Usar “Erro não identificado” quando não houver evidência suficiente para classificar.

**Pronto quando:** a mensagem permanece ligada ao item correto; tentar novamente preserva o histórico útil; o diagnóstico não inclui cookies ou credenciais.

### [ ] 04. Tornar pausa e fechamento mais previsíveis

**Para quê:** evitar travamentos da janela e estados incorretos quando um download é interrompido.

**Situação atual:** `kill_child()` pode executar `taskkill` a partir de ações da interface; o encerramento usa interrupção forçada.

**Implementar:**
- Fazer o controle do processo sem bloquear o Tkinter.
- Distinguir pausando, pausado, baixando e finalizando.
- Usar encerramento cooperativo quando possível e encerramento forçado como alternativa com tempo limite.
- Ao fechar, salvar o estado recuperável e encerrar também os processos filhos.
- Explicar que a retomada depende do site e pode repetir a conversão.

**Pronto quando:** pausar logo após iniciar, pausar durante combinação, fechar durante download e reabrir não deixam processos órfãos nem itens falsamente concluídos. Arquivos parciais úteis são preservados.

## Etapa 2 — Uso diário

### [ ] 05. Progresso, velocidade e tempo restante

**Para quê:** mostrar o que o programa está fazendo sem exigir leitura do painel técnico.

**Implementar:**
- Barra de progresso, bytes recebidos, total estimado, velocidade e tempo restante.
- Distinguir consulta ao site, download de vídeo, download de áudio e finalização.
- Preferir eventos ou saída estruturada do yt-dlp a expressões regulares sobre mensagens humanas.
- Mostrar progresso indeterminado quando o total não for conhecido; não apresentar 100% como conclusão antes do pós-processamento.

**Pronto quando:** um download com áudio e vídeo separados mostra suas etapas corretamente, valores desconhecidos não são inventados e o MP3 só aparece concluído depois da conversão.

### [ ] 06. Consultar informações antes de baixar

**Para quê:** confirmar que o link corresponde ao vídeo desejado e escolher opções disponíveis.

**Implementar:**
- Ação “Consultar vídeo”, com título, duração e origem; miniatura é opcional.
- Consulta em segundo plano, cancelável e com tempo limite.
- Descartar respostas antigas quando o usuário troca o link.
- Exibir formatos realmente disponíveis; explicar quando tamanho ou duração não são informados pelo site.

**Pronto quando:** a consulta não congela a janela nem inicia o download; trocar rapidamente de link não mostra dados do vídeo anterior. Falhas de consulta têm mensagem clara.

### [ ] 07. Adicionar vários links e evitar duplicatas

**Para quê:** facilitar uma lista de vídeos sem adicionar o mesmo item por engano.

**Implementar:**
- Entrada de vários links, um por linha, com prévia dos válidos e inválidos.
- Aviso para links repetidos na mesma entrada ou já presentes na fila.
- Permitir baixar novamente por escolha explícita; considerar qualidade e pasta.
- Não remover parâmetros arbitrariamente de URLs: eles podem identificar o vídeo ou ser necessários para acesso.
- Não transformar automaticamente um link individual em download de playlist.

**Pronto quando:** links válidos são adicionados uma única vez, links inválidos são identificados e a confirmação informa quantos itens entrarão na fila.

### [ ] 08. Escolher formato e encontrar o arquivo

**Para quê:** facilitar o uso do vídeo no celular, editor ou player e localizar o resultado.

**Implementar:**
- Opções compreensíveis como “Melhor qualidade”, “MP4 compatível” e “Áudio MP3”.
- Explicar a diferença entre mudar o contêiner e converter codecs; renomear a extensão não converte o arquivo.
- Para MP4 compatível, selecionar codecs compatíveis quando disponíveis e explicar quando uma conversão será necessária, com custo de tempo e possível perda de qualidade.
- “Mostrar no Explorador” deve selecionar o arquivo final quando ele existir; sem arquivo, abrir a pasta disponível.
- Oferecer “Abrir arquivo” e “Copiar caminho” para itens concluídos.

**Pronto quando:** o formato corresponde ao conteúdo real, o caminho aponta para o resultado final e arquivos movidos ou apagados recebem aviso amigável. A limpeza da lista continua sem apagar arquivos.

## Etapa 3 — Organização

### [ ] 09. Deixar a interface confortável em telas pequenas

**Para quê:** manter todos os controles acessíveis, especialmente os botões de limpar lista e abrir pasta.

**Implementar:**
- Organizar ações principais e secundárias, com adaptação ao tamanho da janela.
- Desabilitar ações que não fazem sentido para o item selecionado.
- Melhorar contraste, foco pelo teclado e ordem de navegação por Tab.
- Guardar tamanho da janela e preferências; restaurar a janela dentro da área visível.
- Oferecer tema escuro como melhoria opcional depois de resolver a legibilidade.

**Pronto quando:** controles essenciais ficam acessíveis em 1366×768 e com escala do Windows em 100%, 125% e 150%; a interface permite navegar por teclado e não depende só de cores para indicar estados.

### [ ] 10. Organizar e controlar a fila

**Para quê:** encontrar itens e controlar a ordem de execução.

**Implementar:**
- Buscar por título ou link e filtrar por pendentes, pausados, concluídos e erros.
- Reordenar apenas itens ainda não iniciados.
- Adicionar “Pausar todos” e “Retomar pendentes”, com significado claro.
- Manter um download por vez como padrão; adiar paralelismo até que cada processo tenha controle independente.
- Separar histórico de concluídos da fila ativa na apresentação, sem perder dados na migração.

**Pronto quando:** filtros não modificam os dados, a ordem escolhida é respeitada, pausar todos impede novos inícios e limpar concluídos preserva pendentes e arquivos.

## Etapa 4 — Distribuição

### [ ] 11. Distribuir uma versão identificável

**Para quê:** permitir que outra pessoa instale a versão correta e reconheça se está usando uma versão antiga.

**Implementar:**
- Adicionar número de versão e janela “Sobre”.
- Documentar instalação, atualização, desinstalação e local do histórico.
- Preparar pacote Windows com todos os arquivos necessários, instruções e checksum SHA-256.
- Preparar notas de versão ligadas ao commit correspondente.
- Conferir avisos e licenças dos componentes redistribuídos; a licença do código próprio depende de decisão do proprietário.
- Preparar uma release para revisão; publicar binários somente quando houver autorização para essa distribuição.

**Pronto quando:** alguém consegue instalar seguindo o README, abrir o programa e identificar sua versão. Atualizar o aplicativo preserva a fila e não exige copiar arquivos individuais de dentro do pacote.

### [ ] 12. Facilitar manutenção e atualizações

**Para quê:** reduzir o trabalho para corrigir mudanças dos sites e evitar que pequenas alterações quebrem outras partes.

**Implementar:**
- Separar gradualmente persistência, execução de downloads e interface, conforme as tarefas exigirem; evitar uma grande reescrita.
- Criar verificações para montagem dos comandos, migração da fila e transições de estado.
- Usar um vídeo local controlado para o fluxo de download e conversão; não depender exclusivamente de sites externos nos testes.
- Documentar como atualizar yt-dlp e gerar uma nova versão.
- Se houver busca de atualização, começar com aviso e link de release; downloads de executáveis precisam de origem verificável e validação de integridade.

**Pronto quando:** os caminhos pelo Python e pelo aplicativo empacotado continuam documentados e verificados; alterações de dependências têm versões registradas e resultado de validação.

## Futuro opcional

### [ ] 13. Playlists com seleção de itens

**Para quê:** baixar vários vídeos de uma coleção de forma controlada.

**Implementar:** consultar a coleção, mostrar quantidade e permitir selecionar itens antes de adicioná-los; estabelecer limite inicial de consulta; lidar com vídeos indisponíveis e duplicados.

**Dependências:** tarefas 06, 07 e 10.

**Pronto quando:** colar uma playlist não começa a baixar tudo automaticamente; o usuário confirma os itens e o cancelamento da consulta funciona.

### [ ] 14. Adaptar para Linux e macOS

**Para quê:** executar o aplicativo em outros sistemas, se esse for um objetivo do proprietário.

**Implementar:** abstrair abertura de pastas, localização do FFmpeg, diretório de dados, controle de processos, instância única e empacotamento. Hoje existem dependências de Windows como `os.startfile`, `taskkill`, `CREATE_NO_WINDOW` e `ffmpeg.exe`.

**Pronto quando:** houver validação real em cada sistema anunciado. Até lá, apresentar o produto como aplicativo Windows com suporte a diferentes sites.

## Prompt pronto para entregar a outro GPT

> Trabalhe no repositório https://github.com/peterson1dhon/videolivre. Leia o README, MELHORIAS.md e as instruções locais aplicáveis. Confira o código atual antes de decidir o que falta. Comece pela primeira tarefa pendente da Etapa 1 e implemente uma tarefa por vez. Preserve a fila existente, os arquivos baixados, a interface em português e os caminhos de execução por Python e pelo aplicativo empacotado. Não duplique os recursos já existentes. Use os critérios de conclusão da tarefa para orientar a implementação e a verificação. Não marque como concluído algo que não verificou; registre limitações e verificações que dependem de ambiente externo. Atualize este documento e o README quando o comportamento mudar. Ao entregar, explique o que mudou, como usar, o que foi verificado e qual é a próxima tarefa. Prepare alterações em commits pequenos; respeite a autorização existente para publicação e não publique binários ou altere a licença sem autorização específica.

## Registro de entregas

Para cada tarefa concluída, acrescente:

- Número e nome da tarefa.
- Commit ou pull request.
- Mudança visível para o usuário.
- Verificações realizadas e resultado.
- Limitações e pendências.

Nenhuma tarefa de implementação foi concluída pela criação deste documento.
