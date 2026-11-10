package br.com.videolivre.android

import java.net.URI
import java.text.Normalizer
import java.util.Locale

enum class Quality(val label: String, val height: Int? = null) {
    BEST("Melhor disponível"), HD1080("Até 1080p", 1080), HD720("Até 720p", 720),
    SD480("Até 480p", 480), MP3("Áudio MP3");

    fun format(): String {
        if (this == MP3) return "bestaudio/best"
        val limit = height?.let { "[height<=$it]" }.orEmpty()
        return "bestvideo$limit+bestaudio/best$limit"
    }
}

enum class State(val label: String) {
    QUEUED("Na fila"), RUNNING("Baixando"), SAVING("Salvando arquivo"),
    PAUSED("Pausado"), CANCELLED("Cancelado"), FAILED("Falhou"), DONE("Concluído");

    val canRetry get() = this == PAUSED || this == CANCELLED || this == FAILED
    val canStop get() = this == RUNNING || this == QUEUED
    fun recovered() = when (this) {
        RUNNING, SAVING -> PAUSED
        else -> this
    }
}

data class Download(
    val id: String,
    val url: String,
    val credit: String,
    val quality: Quality,
    val state: State = State.QUEUED,
    val name: String? = null,
    val uri: String? = null,
    val error: String? = null,
)

fun validLink(value: String): String? = runCatching {
    val url = URI(value.trim())
    require(url.scheme?.lowercase(Locale.ROOT) in setOf("https", "http"))
    require(!url.host.isNullOrEmpty() && url.userInfo == null)
    url.toString()
}.getOrNull()

fun sharedLink(text: String): String? = validLink(text) ?: Regex("""https?://[^\s<>"\u00ab\u00bb]+""", RegexOption.IGNORE_CASE)
    .findAll(text)
    .firstNotNullOfOrNull { validLink(it.value.trimEnd('.', ',', ';', ')', ']', '}', '!', '?')) }

private fun clean(text: String) = Normalizer.normalize(text, Normalizer.Form.NFC)
    .replace(Regex("""[\\/:*?"<>|\p{Cc}\u202A-\u202E\u2066-\u2069]"""), " ")
    .replace(Regex("""\s+"""), " ").trim(' ', '.')

fun normalizeCredit(text: String) = clean(text.replace('[', ' ').replace(']', ' ')).trimStart('@', ' ').trimEnd(' ', '.')
    .let { fitBytes(it, 64) }
    .trimEnd(' ', '.')

private fun fitBytes(value: String, maxBytes: Int): String {
    var index = 0
    var size = 0
    while (index < value.length) {
        val point = value.codePointAt(index)
        val next = index + Character.charCount(point)
        size += value.substring(index, next).toByteArray(Charsets.UTF_8).size
        if (size > maxBytes) break
        index = next
    }
    return value.substring(0, index)
}

private fun automaticCredit(profileUrl: String, channelUrl: String, uploaderId: String): String {
    val handle = Regex("""[\p{L}\p{M}\p{N}._-]{2,60}""")
    fun fromUrl(url: String): String? {
        val profile = runCatching { URI(url) }.getOrNull() ?: return null
        val host = profile.host?.lowercase(Locale.ROOT) ?: return null
        if (profile.scheme !in setOf("https", "http")) return null
        val segments = profile.path.orEmpty().split('/').filter(String::isNotBlank)
        val explicit = segments.firstOrNull { it.startsWith('@') }
        if (explicit != null) return explicit
        val first = segments.singleOrNull() ?: return null
        return first.takeIf {
            (host == "instagram.com" || host.endsWith(".instagram.com")) &&
                it.lowercase(Locale.ROOT) !in setOf("accounts", "explore", "reel", "reels", "stories", "about", "p")
        }
    }
    return sequenceOf(fromUrl(channelUrl), fromUrl(profileUrl), uploaderId.takeIf { it.startsWith('@') })
        .filterNotNull()
        .map(::normalizeCredit)
        .firstOrNull { it.matches(handle) && it.any(Char::isLetter) }
        .orEmpty()
}

data class MediaName(
    val title: String,
    val extension: String,
    val credit: String,
) {
    fun candidate(number: Int): String {
        val suffix = if (number > 1) " ($number)" else ""
        val attribution = if (credit.isBlank()) "" else " [@$credit]"
        val ending = "$suffix$attribution.$extension"
        val stem = fitBytes(title, 200 - ending.toByteArray(Charsets.UTF_8).size).trimEnd(' ', '.')
        return stem + ending
    }

    fun available(existing: Set<String>): String {
        val folded = existing.mapTo(hashSetOf()) { Normalizer.normalize(it, Normalizer.Form.NFC).lowercase(Locale.ROOT) }
        return generateSequence(1) { it + 1 }.map(::candidate)
            .first { it.lowercase(Locale.ROOT) !in folded }
    }
}

fun mediaName(title: String, id: String, ext: String, manual: String, profile: String, uploaderId: String, channel: String = ""): MediaName {
    val numericId = id.takeIf { it.isNotBlank() && it.all(Char::isDigit) }?.let(Regex::escape)
    val stripped = numericId?.let {
        title.replace(Regex("""\s*(?:\[$it\]|\($it\))\s*$"""), "")
            .replace(Regex("""(?<!\d)$it(?!\d)"""), "")
    } ?: title
    return MediaName(
        clean(stripped).ifBlank { "Vídeo" },
        ext.lowercase(Locale.ROOT).takeIf { it.matches(Regex("[a-z0-9]{1,8}")) } ?: "bin",
        normalizeCredit(manual).ifBlank { automaticCredit(profile, channel, uploaderId) },
    )
}
