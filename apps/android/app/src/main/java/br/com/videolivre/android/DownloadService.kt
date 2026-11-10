package br.com.videolivre.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

data class DownloadProgress(val id: String, val percent: Int?, val message: String)

class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val store by lazy { QueueStore.get(this) }
    private val engine by lazy { LocalEngine(this) }
    private val publisher by lazy { DownloadsPublisher(this, store) }
    private val notifications by lazy { getSystemService(NotificationManager::class.java) }
    private var loop: Job? = null
    private var activeId: String? = null
    private var control: TransferControl? = null
    private var latestStart = 0
    private var ending = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL, "Downloads do VideoLivre", NotificationManager.IMPORTANCE_LOW),
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        latestStart = startId
        try {
            startForeground(NOTIFICATION_ID, notification(mutableProgress.value), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } catch (error: IllegalStateException) {
            Log.w("VideoLivre", "O Android não permitiu iniciar o serviço", error)
            stopSelf(startId)
            return START_NOT_STICKY
        }

        val id = intent?.getStringExtra(EXTRA_ID)
        when (intent?.action) {
            ACTION_STOP -> {
                if (id == activeId) control?.stop(State.CANCELLED)
                else store.downloads.value.firstOrNull { it.id == id && it.state == State.QUEUED }?.let {
                    store.put(it.copy(state = State.CANCELLED))
                }
            }
            ACTION_RETRY -> store.downloads.value.firstOrNull { it.id == id && it.state.canRetry }?.let {
                store.put(it.copy(state = State.QUEUED, error = null))
            }
        }

        if (loop?.isActive != true && !ending) loop = scope.launch { runQueue() }
        return START_NOT_STICKY
    }

    private suspend fun runQueue() {
        while (!ending) {
            val item = store.downloads.value.firstOrNull { it.state == State.QUEUED } ?: break
            val transfer = TransferControl()
            activeId = item.id
            control = transfer
            store.put(item.copy(state = State.RUNNING))
            val directory = File(noBackupFilesDir, "parciais/${item.id}")
            update(item.id, null, "Preparando download")

            val finished = withContext(Dispatchers.IO) {
                try {
                    publisher.published(item) ?: run {
                        var lastUpdate = 0L
                        engine.run(item, directory, transfer) { percent ->
                            val now = SystemClock.elapsedRealtime()
                            if (percent == null || now - lastUpdate >= 500) {
                                lastUpdate = now
                                update(item.id, percent, if (percent == null) "Processando mídia" else "Baixando")
                            }
                        }.let { media ->
                            transfer.checkStopped()
                            val saving = item.copy(state = State.SAVING)
                            store.put(saving)
                            update(item.id, null, "Salvando em Downloads")
                            publisher.publish(saving, media, transfer)
                        }
                    }
                } catch (error: Exception) {
                    Log.w("VideoLivre", "Falha em uma transferência (${error.javaClass.simpleName})")
                    val current = store.downloads.value.first { it.id == item.id }
                    current.copy(
                        state = transfer.stopped ?: State.FAILED,
                        error = if (transfer.stopped == null) friendlyError(error) else null,
                    )
                }
            }
            store.put(finished)
            if (finished.state == State.DONE) {
                withContext(Dispatchers.IO) { directory.deleteRecursively() }
            }
            activeId = null
            control = null
        }
        mutableProgress.value = null
        stopSelfResult(latestStart)
    }

    private fun update(id: String, percent: Int?, message: String) {
        val progress = DownloadProgress(id, percent?.coerceIn(0, 100), message)
        mutableProgress.value = progress
        notifications.notify(NOTIFICATION_ID, notification(progress))
    }

    private fun notification(progress: DownloadProgress?): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("VideoLivre")
            .setContentText(progress?.let { p -> p.percent?.let { "${p.message} · $it%" } ?: p.message } ?: "Preparando fila")
            .setContentIntent(open)
            .setProgress(100, progress?.percent ?: 0, progress?.percent == null)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .build()
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        ending = true
        interruptActive()
        stopSelf()
    }

    private fun interruptActive() {
        control?.stop(State.PAUSED)
        activeId?.let { id ->
            store.downloads.value.firstOrNull { it.id == id && it.state in setOf(State.RUNNING, State.SAVING) }
                ?.let { store.put(it.copy(state = State.PAUSED)) }
        }
    }

    override fun onDestroy() {
        interruptActive()
        scope.cancel()
        mutableProgress.value = null
        super.onDestroy()
    }

    companion object {
        const val ACTION_RUN = "br.com.videolivre.android.RUN"
        const val ACTION_STOP = "br.com.videolivre.android.STOP"
        const val ACTION_RETRY = "br.com.videolivre.android.RETRY"
        const val EXTRA_ID = "download"
        private const val CHANNEL = "downloads"
        private const val NOTIFICATION_ID = 10
        private val mutableProgress = MutableStateFlow<DownloadProgress?>(null)
        val progress = mutableProgress.asStateFlow()
    }
}

private fun friendlyError(error: Exception): String {
    if (error is SecurityException) return "O Android bloqueou o acesso ao arquivo. Verifique o armazenamento e tente retomar."
    if (error !is EngineFailure) {
        val detail = error.message.orEmpty()
        return when {
            detail.contains("ENOSPC", true) -> "Espaço insuficiente. Libere espaço e tente retomar."
            detail.startsWith("Motor indisponível") -> detail
            else -> "Não foi possível processar ou salvar o arquivo. Confira o espaço livre e tente retomar."
        }
    }
    val detail = error.detail.lowercase(Locale.ROOT)
    return when {
        "drm" in detail -> "Este conteúdo tem proteção DRM."
        "unsupported url" in detail || "no suitable extractor" in detail -> "O motor não reconheceu este link."
        listOf("private", "sign in", "login", "age-restricted", "bot", "cookies").any { it in detail } ->
            "O site pediu login ou restringiu este conteúdo. Confira se o link é público."
        "403" in detail || "429" in detail -> "O site recusou ou limitou a solicitação. Tente mais tarde."
        "requested format" in detail || "no video formats" in detail ->
            "A qualidade escolhida não está disponível para este link. Adicione novamente com outra opção."
        "timed out" in detail || "network" in detail || "connection" in detail ->
            "A conexão com o site falhou. Confira a internet e tente retomar."
        "404" in detail || "unavailable" in detail -> "O vídeo está indisponível. Confira o link."
        "no space" in detail -> "Espaço insuficiente. Libere espaço e tente retomar."
        "ffmpeg" in detail || "ffprobe" in detail -> "O motor não conseguiu combinar ou converter esta mídia."
        else -> "O motor não conseguiu baixar o conteúdo. Confira o link ou tente outra qualidade."
    }
}
