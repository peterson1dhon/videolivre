# Componentes e licenças

O build busca os artefatos fixados em `app/build.gradle.kts`. Somente os programas nativos e os respectivos pacotes de runtime são extraídos dos AARs. O código JVM GPL do wrapper, seu atualizador e o aria2c ficam fora do APK.

| Componente | Origem e licença |
| --- | --- |
| yt-dlp 2026.10.26 | Zip oficial com Python externo. Código sob Unlicense. [Release e fontes](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26) |
| yt-dlp-ejs 0.8.0 | Wheel da PyPI. Unlicense, com dependências MIT e ISC. [Pacote e distribuição-fonte](https://pypi.org/project/yt-dlp-ejs/0.8.0/) · [Licenças](https://github.com/yt-dlp/ejs/blob/main/LICENSE) |
| Python 3.12.11 e bibliotecas | Artefato [library 0.18.1](https://central.sonatype.com/artifact/io.github.junkfood02.youtubedl-android/library/0.18.1) do youtubedl-android. [Licença da PSF](https://docs.python.org/3.12/license.html) · [Receita upstream](https://github.com/JunkFood02/youtubedl-android/blob/0.17.2/BUILD_PYTHON.md) |
| QuickJS 2025-04-26 | Executável do mesmo artefato `library`. [Projeto e licença MIT](https://bellard.org/quickjs/) |
| FFmpeg e ffprobe 7.1.1, com bibliotecas | Artefato [ffmpeg 0.18.1](https://central.sonatype.com/artifact/io.github.junkfood02.youtubedl-android/ffmpeg/0.18.1) do youtubedl-android, O binário x86_64 reporta GPL-3.0-or-later, com `--enable-gpl` e `--enable-version3`. [Receita upstream](https://github.com/JunkFood02/youtubedl-android/blob/0.17.2/BUILD_FFMPEG.md) · [Fontes oficiais do FFmpeg 7.1.1](https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz) · [Licenciamento FFmpeg](https://ffmpeg.org/legal.html) |
| Kotlin e AndroidX/Compose | [Kotlin](https://github.com/JetBrains/kotlin/blob/master/license/LICENSE.txt) e [AndroidX](https://github.com/androidx/androidx/blob/androidx-main/LICENSE.txt), Apache-2.0. |

Os AARs também contêm bibliotecas de terceiros com licenças próprias. O material acima identifica as origens. A tag pública 0.17.2 do fornecedor documenta a receita, mas não estabelece o código-fonte correspondente exato de todos os binários do AAR 0.18.1. Antes de redistribuir o APK fora de testes privados, reúna os avisos, as licenças e o código-fonte correspondente das dependências copyleft ou recompile o runtime com fontes e receitas fixadas. Nenhum APK é publicado pelo repositório.
