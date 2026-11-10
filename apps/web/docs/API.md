# API VideoLivre Web v1

Base `/api/v1`. Use o HTTPS do Serve ao acessar de outro dispositivo. O app é de uso pessoal e a chave representa o proprietário de toda a fila. Guarde a chave em armazenamento seguro do cliente. Nunca inclua a chave em URLs.

## Autenticação

- Clientes nativos enviam `Authorization: Bearer <chave>` nas rotas protegidas.
- Navegadores enviam `POST /session` com JSON `{"key":"…"}`, `Content-Type: application/json` e `X-VideoLivre: 1`. O sucesso devolve `204` e cookie de sessão `HttpOnly; Secure; SameSite=Strict`. Mutações autenticadas pelo cookie exigem `X-VideoLivre: 1`. O cookie expira em 12 horas, com máximo de 16 sessões simultâneas. O login limita tentativas inválidas.
- `DELETE /session` encerra a sessão de navegador. Credenciais Bearer permanecem válidas até a chave ser trocada com o serviço parado.
- `GET /info` é público. Exemplo de resposta `{"version":"0.1.0","api":"v1"}`.

## Fila

| Método e rota | Resposta |
| --- | --- |
| `GET /jobs` | `200`, lista de itens em ordem de fila |
| `POST /jobs` | `201`, item criado |
| `POST /jobs/{id}/cancel` | `204`, cancelamento aceito ou já em curso |
| `POST /jobs/{id}/resume` | `204`, item cancelado ou com falha volta ao fim da fila |
| `GET /jobs/{id}/file` | `200` com arquivo concluído, ou `206` com Range válido |
| `HEAD /jobs/{id}/file` | Cabeçalhos da resposta do arquivo concluído |
| `DELETE /jobs/{id}` | `204`, remove um registro terminal e seu parcial |
| `DELETE /jobs` | `204`, limpa registros terminais e seus parciais |

Envie a criação como JSON. `credit` pode ser omitido ou `null`. `quality` é uma string com valor `best`, `1080`, `720`, `480` ou `mp3`.

```json
{"url":"https://example.org/video.mp4","quality":"720","credit":"@João Vídeos"}
```

Cada item contém `id` (UUID), `url`, `quality`, `credit`, `title`, `creator`, `status`, `stage`, `progress`, `error`, `filename` e `created_at` (segundos Unix). `credit`, `title`, `creator`, `stage`, `progress`, `error` e `filename` podem ser nulos. `stage` assume `extract`, `download` ou `convert`. `progress` é um inteiro de 0 a 100 para o estágio atual e pode voltar a zero ao baixar a próxima trilha. `status` assume `queued`, `running`, `cancelling`, `cancelled`, `failed` ou `completed`. Consulte a fila a cada 2 segundos enquanto o cliente estiver ativo.

O arquivo exige autorização própria a cada pedido, inclusive para Range. Respeite `Content-Disposition` e seu `filename*` em UTF-8. Após remover o registro, a API deixa de servir aquele arquivo. O original finalizado permanece no disco.

Erros da aplicação usam `{"error":"…"}`. Códigos usuais incluem `400` para entrada inválida, `401` para falta de autorização, `403` para a proteção da sessão, `404` para item indisponível, `409` para estado ou capacidade incompatível e `429` para tentativas de login. Erros de JSON ou UUID podem retornar texto do framework. Limite de corpo JSON de 8 KiB. Limites de fila de 12 ativos e 60 registros.
