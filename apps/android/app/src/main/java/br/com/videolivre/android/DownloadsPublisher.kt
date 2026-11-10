package br.com.videolivre.android

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.provider.MediaStore.MediaColumns
import android.webkit.MimeTypeMap
import java.io.IOException

class DownloadsPublisher(context: Context, private val store: QueueStore) {
    private val resolver = context.contentResolver
    private val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
    private val path = "${Environment.DIRECTORY_DOWNLOADS}/VideoLivre/"

    fun publish(item: Download, media: StagedMedia, control: TransferControl): Download {
        val previous = item.uri?.let(Uri::parse)
        val pending = previous?.let(::isPending)
        if (previous != null && pending == false) return actualName(item, previous)

        val target = mediaName(media.title, media.id, media.ext, item.credit, media.profile, media.uploader, media.channel)
        val tempName = "VideoLivre-${item.id}.${target.extension}"
        val name = target.available(inFolder(MediaColumns.DISPLAY_NAME).use { cursor ->
            buildSet { while (cursor.moveToNext()) add(cursor.getString(0)) }
        })
        val uri = previous?.takeIf { pending == true } ?: findTemp(tempName) ?: createTemp(tempName, target.extension)
        val saving = item.copy(uri = uri.toString(), name = name)
        store.put(saving)

        resolver.openOutputStream(uri, "wt")?.use { output ->
            media.file.inputStream().use { input ->
                val buffer = ByteArray(128 * 1024)
                while (true) {
                    control.checkStopped()
                    val count = input.read(buffer)
                    if (count == -1) break
                    output.write(buffer, 0, count)
                }
            }
        } ?: throw IOException("O Android não abriu o arquivo de destino.")
        control.checkStopped()
        val update = ContentValues().apply {
            put(MediaColumns.DISPLAY_NAME, name)
            put(MediaColumns.IS_PENDING, 0)
        }
        if (resolver.update(uri, update, null, null) != 1) {
            throw IOException("O Android não conseguiu publicar o arquivo em Downloads.")
        }
        return actualName(saving, uri)
    }

    fun published(item: Download): Download? {
        val uri = item.uri?.let(Uri::parse) ?: return null
        return if (isPending(uri) == false) actualName(item, uri) else null
    }

    private fun actualName(item: Download, uri: Uri): Download {
        val name = resolver.query(uri, arrayOf(MediaColumns.DISPLAY_NAME), null, null, null)
            ?.use { if (it.moveToFirst()) it.getString(0) else null }
        return item.copy(uri = uri.toString(), name = name ?: item.name, state = State.DONE, error = null)
    }

    @Suppress("DEPRECATION")
    private fun isPending(uri: Uri): Boolean? =
        resolver.query(MediaStore.setIncludePending(uri), arrayOf(MediaColumns.IS_PENDING), null, null, null)
            ?.use { if (it.moveToFirst()) it.getInt(0) == 1 else null }

    private fun findTemp(name: String): Uri? = inFolder(MediaColumns._ID, name).use {
        if (it.moveToFirst()) ContentUris.withAppendedId(collection, it.getLong(0)) else null
    }

    private fun createTemp(name: String, extension: String): Uri {
        val values = ContentValues().apply {
            put(MediaColumns.RELATIVE_PATH, path)
            put(MediaColumns.DISPLAY_NAME, name)
            put(MediaColumns.IS_PENDING, 1)
            put(MediaColumns.MIME_TYPE, mediaType(extension))
        }
        return resolver.insert(collection, values) ?: throw IOException("Não foi possível criar o arquivo em Downloads.")
    }

    @Suppress("DEPRECATION")
    private fun inFolder(column: String, name: String? = null): android.database.Cursor {
        val selection = "${MediaColumns.RELATIVE_PATH} = ?" +
            if (name != null) " AND ${MediaColumns.DISPLAY_NAME} = ? AND ${MediaColumns.IS_PENDING} = 1" else ""
        val args = if (name != null) arrayOf(path, name) else arrayOf(path)
        return resolver.query(MediaStore.setIncludePending(collection), arrayOf(column), selection, args, null)
            ?: throw IOException("O Android não conseguiu consultar a pasta Downloads.")
    }
}

fun mediaType(extension: String): String = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension)
    ?: when (extension) {
        "mkv" -> "video/x-matroska"
        else -> "application/octet-stream"
    }
