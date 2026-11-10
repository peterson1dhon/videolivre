package br.com.videolivre.android

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

class QueueStore(context: Context) : SQLiteOpenHelper(context, "fila.db", null, 1) {
    private val rows = MutableStateFlow<List<Download>>(emptyList())
    val downloads = rows.asStateFlow()

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE downloads (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, credit TEXT NOT NULL,
                quality TEXT NOT NULL, state TEXT NOT NULL, name TEXT, uri TEXT, error TEXT
            )
        """.trimIndent())
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    init {
        read().filter { it.state.recovered() != it.state }.forEach {
            write(it.copy(state = it.state.recovered()))
        }
        refresh()
    }

    @Synchronized
    fun put(item: Download) {
        write(item)
        refresh()
    }

    @Synchronized
    fun clearHistory() {
        writableDatabase.delete("downloads", "state = ?", arrayOf(State.DONE.name))
        refresh()
    }

    private fun write(item: Download) {
        val values = ContentValues().apply {
            put("url", item.url)
            put("credit", item.credit)
            put("quality", item.quality.name)
            put("state", item.state.name)
            put("name", item.name)
            put("uri", item.uri)
            put("error", item.error)
        }
        if (writableDatabase.update("downloads", values, "id = ?", arrayOf(item.id)) == 0) {
            values.put("id", item.id)
            writableDatabase.insertOrThrow("downloads", null, values)
        }
    }

    private fun refresh() {
        rows.value = read()
    }

    private fun read(): List<Download> = readableDatabase.rawQuery(
        "SELECT id, url, credit, quality, state, name, uri, error FROM downloads ORDER BY rowid", null,
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) add(Download(
                cursor.getString(0), cursor.getString(1), cursor.getString(2),
                Quality.valueOf(cursor.getString(3)), State.valueOf(cursor.getString(4)),
                cursor.getString(5), cursor.getString(6), cursor.getString(7),
            ))
        }
    }

    companion object {
        @Volatile private var instance: QueueStore? = null

        fun get(context: Context): QueueStore = instance ?: synchronized(this) {
            instance ?: QueueStore(context.applicationContext).also { instance = it }
        }
    }
}
