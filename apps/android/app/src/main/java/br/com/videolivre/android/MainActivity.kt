package br.com.videolivre.android

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import java.util.UUID

class MainActivity : ComponentActivity() {
    private val store by lazy { QueueStore.get(this) }
    private var draft by mutableStateOf("")
    private var credit by mutableStateOf("")
    private var linkError by mutableStateOf<String?>(null)
    private var feedback by mutableStateOf<String?>(null)
    private var shareCount by mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        draft = savedInstanceState?.getString("draft").orEmpty()
        credit = savedInstanceState?.getString("credit").orEmpty()
        if (savedInstanceState == null) receive(intent)
        setContent {
            val colors = if (isSystemInDarkTheme()) darkColorScheme(
                primary = Color(0xFF79D8C7),
                primaryContainer = Color(0xFF005047),
                onPrimary = Color(0xFF00382F),
                onPrimaryContainer = Color(0xFFB0F4E6),
                secondaryContainer = Color(0xFF304941),
                onSecondaryContainer = Color(0xFFD4EAE1),
                background = Color(0xFF121C1B),
                onBackground = Color(0xFFE1ECE9),
                surface = Color(0xFF121C1B),
                onSurface = Color(0xFFE1ECE9),
                onSurfaceVariant = Color(0xFFBCCDC7),
                outline = Color(0xFF8B9F97),
                outlineVariant = Color(0xFF455950),
            ) else lightColorScheme(
                primary = Color(0xFF076B61),
                primaryContainer = Color(0xFFB9F0E4),
                onPrimaryContainer = Color(0xFF002D27),
                secondaryContainer = Color(0xFFD9EAE5),
                onSecondaryContainer = Color(0xFF183932),
                background = Color(0xFFF3F5F7),
                onBackground = Color(0xFF182B3A),
                surface = Color(0xFFF3F5F7),
                onSurface = Color(0xFF182B3A),
                onSurfaceVariant = Color(0xFF465D61),
                outline = Color(0xFF697C80),
                outlineVariant = Color(0xFFC4CFD1),
            )
            MaterialTheme(colorScheme = colors) { Home() }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("draft", draft)
        outState.putString("credit", credit)
        super.onSaveInstanceState(outState)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        receive(intent)
    }

    private fun receive(intent: Intent) {
        if (intent.action != Intent.ACTION_SEND) return
        val text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString().orEmpty()
        val link = sharedLink(text)
        shareCount++
        if (link == null) {
            linkError = "O conteúdo compartilhado não contém um link HTTP ou HTTPS."
        } else {
            if (draft != link) credit = ""
            updateDraft(link)
        }
    }

    private fun updateDraft(value: String) {
        if (draft != value && validLink(draft) != null) credit = ""
        draft = value
        linkError = null
    }

    private fun clipboard(): String = getSystemService(ClipboardManager::class.java)
        .primaryClip?.getItemAt(0)?.text?.toString().orEmpty()

    private fun send(action: String, id: String? = null): Boolean {
        return runCatching {
            startForegroundService(Intent(this, DownloadService::class.java).apply {
                this.action = action
                putExtra(DownloadService.EXTRA_ID, id)
            })
            true
        }.getOrElse {
            feedback = "O Android não iniciou a fila. Toque em Iniciar fila para tentar novamente."
            false
        }
    }

    private fun add(quality: Quality): Boolean {
        val url = validLink(draft)
        if (url == null) {
            linkError = "Informe um link HTTP ou HTTPS completo."
            return false
        }
        store.put(Download(UUID.randomUUID().toString(), url, normalizeCredit(credit), quality))
        draft = ""
        credit = ""
        linkError = null
        send(DownloadService.ACTION_RUN)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED && !getPreferences(MODE_PRIVATE).getBoolean("askedNotifications", false)
        ) {
            getPreferences(MODE_PRIVATE).edit().putBoolean("askedNotifications", true).apply()
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        return true
    }

    private fun fileAction(download: Download, share: Boolean) {
        val uri = download.uri?.let(Uri::parse) ?: return
        try {
            val type = contentResolver.getType(uri) ?: mediaType(download.name.orEmpty().substringAfterLast('.'))
            val fileIntent = if (share) Intent(Intent.ACTION_SEND).apply {
                this.type = type
                putExtra(Intent.EXTRA_STREAM, uri)
                clipData = ClipData.newRawUri("Arquivo do VideoLivre", uri)
            } else Intent(Intent.ACTION_VIEW).setDataAndType(uri, type)
            fileIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            contentResolver.openFileDescriptor(uri, "r")?.use {} ?: error("Arquivo ausente")
            startActivity(if (share) Intent.createChooser(fileIntent, "Compartilhar arquivo") else fileIntent)
        } catch (error: ActivityNotFoundException) {
            feedback = "Nenhum app instalado consegue abrir este formato."
        } catch (error: Exception) {
            feedback = "O arquivo não está mais disponível em Downloads."
        }
    }

    @OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
    @Composable
    private fun Home() {
        val list by store.downloads.collectAsState()
        val progress by DownloadService.progress.collectAsState()
        var quality by rememberSaveable { mutableStateOf(Quality.BEST) }
        var clear by remember { mutableStateOf(false) }
        val focus = LocalFocusManager.current
        val snackbar = remember { SnackbarHostState() }
        val scroll = rememberLazyListState()
        LaunchedEffect(shareCount) {
            if (shareCount > 0) scroll.scrollToItem(0)
        }
        LaunchedEffect(feedback) {
            feedback?.let {
                snackbar.showSnackbar(it)
                feedback = null
            }
        }
        val queue = list.filter { it.state != State.DONE }
        val history = list.filter { it.state == State.DONE }.asReversed()

        Scaffold(
            contentWindowInsets = WindowInsets.safeDrawing,
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                TopAppBar(
                    title = { Text("VideoLivre", fontWeight = FontWeight.SemiBold) },
                    actions = {
                        Text("v${BuildConfig.VERSION_NAME}", Modifier.padding(end = 20.dp),
                            style = MaterialTheme.typography.labelMedium)
                    },
                )
            },
        ) { insets ->
            Box(Modifier.fillMaxSize().padding(insets).imePadding(), contentAlignment = Alignment.TopCenter) {
                LazyColumn(
                    Modifier.widthIn(max = 620.dp).fillMaxWidth().padding(horizontal = 20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    state = scroll,
                ) {
                    item {
                        Surface(
                            color = MaterialTheme.colorScheme.primaryContainer,
                            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                            shape = MaterialTheme.shapes.large,
                        ) {
                            Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text("Novo download", Modifier.semantics { heading() },
                                    style = MaterialTheme.typography.headlineSmall)
                                Text("Cole um link ou compartilhe de outro app.\nDestino: Downloads/VideoLivre",
                                    style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                    item {
                        OutlinedTextField(
                            value = draft, onValueChange = ::updateDraft,
                            label = { Text("Link do vídeo") },
                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                            isError = linkError != null,
                            supportingText = linkError?.let { error -> { Text(error) } },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                            trailingIcon = {
                                TextButton(onClick = {
                                    val link = sharedLink(clipboard())
                                    if (link == null) linkError = "Nenhum link válido na área de transferência."
                                    else updateDraft(link)
                                }) { Text("Colar") }
                            },
                        )
                    }
                    item {
                        OutlinedTextField(
                            value = credit, onValueChange = { credit = it },
                            label = { Text("Crédito do criador (opcional)") },
                            placeholder = { Text("@nome do criador") },
                            supportingText = { Text("Se ficar vazio, usamos o @ quando o site informar.") },
                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    item {
                        Text("Qualidade", style = MaterialTheme.typography.titleSmall)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Quality.entries.forEach { option ->
                                FilterChip(
                                    selected = quality == option,
                                    onClick = { quality = option },
                                    label = { Text(option.label) },
                                )
                            }
                        }
                    }
                    item {
                        Button(onClick = { if (add(quality)) focus.clearFocus() }, modifier = Modifier.fillMaxWidth()) {
                            Text("Adicionar à fila")
                        }
                    }

                    item {
                        Section("Fila", queue.size)
                        if (queue.isEmpty()) Text("Os downloads em andamento aparecem aqui.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                        else if (queue.any { it.state == State.QUEUED } && progress == null) {
                            TextButton(onClick = { send(DownloadService.ACTION_RUN) }) { Text("Iniciar fila") }
                        }
                    }
                    items(queue, key = { it.id }) { item ->
                        QueueEntry(item, progress?.takeIf { it.id == item.id })
                    }
                    item {
                        Section("Histórico", history.size)
                        if (history.isEmpty()) Text("Os arquivos concluídos aparecem aqui.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                        else TextButton(onClick = { clear = true }) { Text("Limpar histórico") }
                    }
                    items(history, key = { it.id }) { item -> QueueEntry(item, null) }
                    item {
                        Text("Baixe apenas conteúdo que você tem permissão para salvar.",
                            Modifier.padding(vertical = 16.dp), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }

        if (clear) AlertDialog(
            onDismissRequest = { clear = false },
            title = { Text("Limpar histórico?") },
            text = { Text("Os arquivos salvos permanecem em Downloads/VideoLivre.") },
            confirmButton = {
                TextButton(onClick = { store.clearHistory(); clear = false }) { Text("Limpar") }
            },
            dismissButton = { TextButton(onClick = { clear = false }) { Text("Voltar") } },
        )
    }

    @Composable
    private fun Section(title: String, count: Int) {
        Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(title, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge)
            Text(count.toString(), style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }

    @Composable
    @OptIn(ExperimentalLayoutApi::class)
    private fun QueueEntry(item: Download, progress: DownloadProgress?) {
        Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
            HorizontalDivider()
            Text(item.name ?: item.url, Modifier.padding(top = 5.dp), maxLines = 2,
                overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleSmall)
            val percent = progress?.percent
            val state = progress?.message ?: item.state.label
            Text("$state${percent?.let { " · $it%" }.orEmpty()} · ${item.quality.label}",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (progress != null) {
                if (percent == null) LinearProgressIndicator(Modifier.fillMaxWidth())
                else LinearProgressIndicator(progress = { percent / 100f }, modifier = Modifier.fillMaxWidth())
            }
            item.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (item.state.canStop) {
                    TextButton(onClick = { send(DownloadService.ACTION_STOP, item.id) }) { Text("Cancelar") }
                }
                if (item.state.canRetry) {
                    TextButton(onClick = { send(DownloadService.ACTION_RETRY, item.id) }) { Text("Retomar") }
                }
                if (item.state == State.DONE) {
                    TextButton(onClick = { fileAction(item, false) }) { Text("Abrir") }
                    TextButton(onClick = { fileAction(item, true) }) { Text("Compartilhar") }
                }
            }
        }
    }
}
