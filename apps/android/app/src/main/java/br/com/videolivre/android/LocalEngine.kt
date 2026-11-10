package br.com.videolivre.android

import android.content.Context
import android.os.Build
import android.system.Os
import android.system.OsConstants
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.zip.ZipInputStream

class LocalEngine(private val context: Context) {
    private val binaries = File(context.applicationInfo.nativeLibraryDir)
    private val root = File(context.noBackupFilesDir, "motor")
    private val runtime = File(root, "${BuildConfig.ENGINE_VERSION}-${BuildConfig.VERSION_CODE}")
    private val complete = File(runtime, "ready")

    private fun prepare(control: TransferControl) {
        if (complete.isFile) return
        if (!File(binaries, "libpython.so").isFile || !File(binaries, "libffmpeg.so").isFile) {
            throw IOException("Motor indisponível para ${Build.SUPPORTED_ABIS.joinToString()}.")
        }
        runtime.deleteRecursively()
        runtime.mkdirs()
        unpack("python", control)
        unpack("ffmpeg", control)
        listOf("yt-dlp", "yt_dlp_ejs.whl").forEach { name ->
            control.checkStopped()
            context.assets.open(name).use { input ->
                File(runtime, name).outputStream().use { input.copyTo(it) }
            }
        }
        complete.writeText("ok")
    }

    private fun unpack(component: String, control: TransferControl) {
        val directory = File(runtime, component).canonicalFile
        val lib = File(directory, "usr/lib")
        ZipInputStream(File(binaries, "lib$component.zip.so").inputStream().buffered()).use { zip ->
            while (true) {
                control.checkStopped()
                val entry = zip.nextEntry ?: break
                val target = File(directory, entry.name).canonicalFile
                check(target.path.startsWith(directory.path + File.separator))
                if (entry.isDirectory) {
                    target.mkdirs()
                } else {
                    checkNotNull(target.parentFile).mkdirs()
                    target.outputStream().buffered().use { zip.copyTo(it) }
                }
            }
        }
        // These pinned upstream archives store relative library links as small text entries.
        lib.listFiles().orEmpty().filter { it.isFile && it.length() in 1L..96L }.forEach { file ->
            val link = file.readText()
            if (link.matches(Regex("""lib[\w.+-]+\.so(?:\.[\w.+-]+)?""")) && File(lib, link).isFile) {
                check(file.delete())
                Os.symlink(link, file.path)
            }
        }
    }

    fun run(job: Download, directory: File, control: TransferControl, onProgress: (Int?) -> Unit): StagedMedia {
        prepare(control)
        control.checkStopped()
        directory.mkdirs()
        val metadata = File(directory, "ready.json")
        if (metadata.isFile) return parseMedia(directory, metadata.readText())

        val options = mutableListOf(
            "--ignore-config", "--no-cache-dir", "--no-playlist", "--max-downloads", "1",
            "--continue", "--no-overwrites", "--newline", "--no-simulate", "--progress",
            "--socket-timeout", "25", "--retries", "3", "--fragment-retries", "3",
            "--no-js-runtimes", "--js-runtimes", "quickjs:${File(binaries, "libqjs.so")}",
            "--ffmpeg-location", File(binaries, "libffmpeg.so").path,
            "--progress-template", "download:VL_PROGRESS:%(progress._percent_str)s",
            "--progress-template", "postprocess:VL_CONVERTING:",
            "--print", "after_move:VL_READY:%(.{filepath,title,id,ext,uploader_url,uploader_id,channel_url})j",
            "-o", "media.%(ext)s", "-f", job.quality.format(),
        )
        if (job.quality == Quality.MP3) {
            options += listOf("-x", "--audio-format", "mp3", "--audio-quality", "0")
        } else {
            options += listOf("--merge-output-format", "mkv")
        }

        val command = listOf(File(binaries, "libpython.so").path, "-u", "-c", """
            import os, runpy, sys
            os.setsid()
            print("VL_PID:" + str(os.getpid()), flush=True)
            sys.argv = sys.argv[1:]
            runpy.run_path(sys.argv[0], run_name="__main__")
        """.trimIndent(), File(runtime, "yt-dlp").path) + options + listOf("--", job.url)
        val builder = ProcessBuilder(command).directory(directory).redirectErrorStream(true)
        builder.environment().apply {
            put("LD_LIBRARY_PATH", "$runtime/python/usr/lib:$runtime/ffmpeg/usr/lib")
            put("PYTHONHOME", "$runtime/python/usr")
            put("PYTHONPATH", "$runtime/yt_dlp_ejs.whl")
            put("PYTHONUTF8", "1")
            put("PYTHONDONTWRITEBYTECODE", "1")
            put("SSL_CERT_FILE", "$runtime/python/usr/etc/tls/cert.pem")
            put("HOME", runtime.path)
            put("TMPDIR", context.cacheDir.path)
        }
        var result: String? = null
        var error = ""
        val process = control.start(builder)
        try {
            process.inputStream.bufferedReader().useLines { lines ->
                lines.forEach { line ->
                    when {
                        line.startsWith("VL_PID:") -> line.substringAfter(':').toIntOrNull()?.let(control::group)
                        line.startsWith("VL_PROGRESS:") ->
                            onProgress(line.substringAfter(':').trim().removeSuffix("%").toFloatOrNull()?.toInt())
                        line.startsWith("VL_CONVERTING:") -> onProgress(null)
                        line.startsWith("VL_READY:") -> result = line.substringAfter(':')
                        line.contains("ERROR:", ignoreCase = true) -> error = line.take(500)
                        error.isBlank() && line.isNotBlank() -> error = line.take(500)
                    }
                }
            }
            val exit = process.waitFor()
            control.checkStopped()
            val raw = result ?: throw EngineFailure(error)
            if (exit != 0 && exit != 101) throw EngineFailure(error)
            val media = parseMedia(directory, raw)
            val marker = File(directory, "ready.tmp")
            marker.writeText(raw)
            check(marker.renameTo(metadata))
            return media
        } finally {
            control.finish()
        }
    }

    private fun parseMedia(directory: File, raw: String): StagedMedia {
        val info = JSONObject(raw)
        fun field(key: String) = if (info.isNull(key)) "" else info.optString(key)
        val path = File(field("filepath"))
        val file = (if (path.isAbsolute) path else File(directory, path.path)).canonicalFile
        check(file.parentFile == directory.canonicalFile && file.name.startsWith("media.") && file.isFile && file.length() > 0)
        return StagedMedia(file, field("title"), field("id"), file.extension, field("uploader_url"), field("uploader_id"), field("channel_url"))
    }
}

data class StagedMedia(val file: File, val title: String, val id: String, val ext: String, val profile: String, val uploader: String, val channel: String)

class EngineFailure(val detail: String) : IOException(detail)

class TransferStopped : IOException()

class TransferControl {
    @Volatile var stopped: State? = null
        private set
    private var process: Process? = null
    private var groupId: Int? = null

    @Synchronized fun start(builder: ProcessBuilder): Process {
        checkStopped()
        return builder.start().also { process = it }
    }

    @Synchronized fun group(pid: Int) {
        if (pid > 1 && process != null && groupId == null) groupId = pid
        if (stopped != null) kill()
    }

    @Synchronized fun stop(state: State) {
        stopped = state
        kill()
    }

    @Synchronized fun finish() {
        kill()
        process = null
        groupId = null
    }

    private fun kill() {
        if (process?.isAlive != true) return
        groupId?.let { runCatching { Os.kill(-it, OsConstants.SIGKILL) } }
        process?.destroyForcibly()
    }

    fun checkStopped() {
        if (stopped != null) throw TransferStopped()
    }
}
