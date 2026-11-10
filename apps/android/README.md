# VideoLivre para Android

App nativo em português para baixar um vídeo ou áudio diretamente no Android. A fila é sequencial e persiste em SQLite. O arquivo concluído aparece na pasta **Downloads/VideoLivre** e pode ser aberto ou compartilhado pelo histórico.

## Uso

1. Use **Colar** ou compartilhe um link de outro app com o VideoLivre. Revise o endereço antes de adicionar.
2. Escolha **Melhor disponível**, um limite de **1080p**, **720p** ou **480p**, ou **Áudio MP3**.
3. Se quiser definir o crédito, informe o nome ou @ do criador. O campo é limpo ao adicionar. Quando vazio, o app usa um @ explícito ou um link de perfil reconhecido fornecido pelo extrator, quando disponível.
4. Toque em **Adicionar à fila**. A notificação acompanha a transferência em segundo plano quando autorizada. **Cancelar** interrompe o item. **Retomar** tenta aproveitar o arquivo parcial quando a fonte aceita.
5. Use **Abrir** ou **Compartilhar** no histórico. **Limpar histórico** remove os registros concluídos e mantém os arquivos.

O nome é `Título [@criador].ext` quando há crédito. O ID numérico do site não é anexado e é removido quando o próprio título inclui o ID reportado. Nomes repetidos recebem um número, por exemplo `Título (2) [@criador].ext`. Acentos e emoji são preservados quando compatíveis com o nome.

## Compilar e instalar o APK de depuração

- JDK 17 ou 21, Android SDK Platform 36 e Build Tools 36.0.0. Aponte `ANDROID_HOME` para o SDK ou configure `sdk.dir` em `local.properties`.
- Execute os comandos a partir de `apps/android`. No Linux ou macOS, use `./gradlew`.

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug
```

Os APKs de depuração ficam em `app/build/outputs/apk/debug/`. O build mediu cerca de 72 MiB para ARM64 e 75 MiB para x86_64. No emulador, a primeira transferência preparou mais 144 MiB de runtime privado. Em **Configurações → Apps → VideoLivre**, a versão também aparece como **0.1.0**, com código **1**. A tela inicial mostra **v0.1.0**. A chave de depuração é específica do ambiente de build e uma assinatura diferente impede a atualização por cima.

| APK | Compatibilidade |
| --- | --- |
| `app-arm64-v8a-debug.apk` | Android 10 ou posterior, ARM de 64 bits |
| `app-x86_64-debug.apk` | Android 10 ou posterior, x86 de 64 bits, incluindo emuladores compatíveis |

Para instalar no seu emulador, substitua o serial pelo mostrado por `adb devices`.

```powershell
adb -s emulator-5554 install -r app/build/outputs/apk/debug/app-x86_64-debug.apk
```

## Motor e compatibilidade

A compatibilidade com aparelhos de página de memória de 16 KB não foi validada. Algumas bibliotecas WebP internas do FFmpeg têm alinhamento ELF de 4 KB. Para dar suporte de distribuição a esses aparelhos, será preciso validar ou substituir o runtime. [Páginas de 16 KB no Android](https://developer.android.com/guide/practices/page-sizes)

- Kotlin/Compose organiza o fluxo. O app executa yt-dlp e FFmpeg no sandbox do Android, com argumentos separados, sem shell e sem importar cookies. Rust oferece segurança de memória para código nativo seguro, mas validação e autenticação continuam sendo controles distintos. O app não precisa de uma camada JNI própria.
- O build fixa versões e hashes dos pacotes. Os executáveis nativos são extraídos pelo Android no momento da instalação. As bibliotecas, scripts e certificados são preparados no armazenamento privado no primeiro download. A versão do motor muda ao compilar e instalar outro APK. O app não baixa código de atualização em execução.
- O FFmpeg combina fluxos separados em MKV e converte áudio para MP3. Um arquivo combinado pode manter o contêiner de origem. A disponibilidade de qualidades, o crédito automático e a retomada dependem do extrator e da fonte. Retomar pode repetir uma etapa de processamento.
- O app aceita um item por link. Sites com DRM, autenticação, verificação de cliente ou restrições geográficas podem impedir a transferência. Use somente para conteúdo que você tem permissão de salvar.
- A tarefa usa um [serviço em primeiro plano do tipo `dataSync`](https://developer.android.com/develop/background-work/services/fgs/timeout). Se o sistema interromper o app, a transferência fica pausada na próxima abertura. Itens que ainda estiverem na fila podem ser iniciados de novo com **Iniciar fila**.
- O resultado passa pelo [MediaStore Downloads](https://developer.android.com/training/data-storage/shared/media) somente depois que a mídia está pronta. Durante a cópia, é necessário espaço livre para o arquivo privado e para a cópia pública.

Consulte [Componentes e licenças](COMPONENTES.md) para ver a origem e as condições de redistribuição dos binários.

## Verificação

- O Gradle Wrapper concluiu `:app:assembleDebug` e os sete testes JVM. Os casos cobrem Unicode, precedência do crédito, IDs numéricos, colisões, entrada de links, seleção de formato e recuperação dos estados da fila.
- No emulador Android 15 x86_64 com páginas de 4 KB, um MP4 de teste entrou pelo compartilhamento do Android. O app salvou o MP4 com e sem crédito manual e converteu a mesma amostra para MP3.
- Em uma transferência lenta, **Cancelar** preservou o parcial. O registro continuou disponível após encerrar e reabrir o app. **Retomar** enviou um intervalo HTTP a partir do parcial e concluiu em segundo plano. O SHA-256 do vídeo retomado coincidiu com o da origem.
- O APK ARM64 foi compilado e teve a assinatura e a arquitetura verificadas. A execução foi testada no emulador x86_64.
- O APK final salvou o segundo arquivo como amostra (2).mp4, abriu o menu de compartilhamento e esvaziou o histórico sem alterar os hashes dos cinco arquivos em Downloads.
