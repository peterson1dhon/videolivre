package br.com.videolivre.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadTest {
    @Test fun manualCreditWinsAndNumericIdIsRemoved() {
        val file = mediaName("Café: manhã 🎬 [123456789]", "123456789", "mp4",
            "@João Gonçalves", "https://example.com/@outra", "@outra")
        assertEquals("Café manhã 🎬 [@João Gonçalves].mp4", file.candidate(1))
    }

    @Test fun automaticCreditRequiresAHandle() {
        assertEquals("Vídeo [@criação].mp4",
            mediaName("Vídeo", "123", "mp4", "", "https://example.com/@cria%C3%A7%C3%A3o", "92838").candidate(1))
        assertEquals("Vídeo [@criação].mp4",
            mediaName("Vídeo", "123", "mp4", "", "", "@criação").candidate(1))
        assertEquals("Vídeo.mp4",
            mediaName("Vídeo", "123", "mp4", "", "https://example.com/channel/123", "123").candidate(1))
    }

    @Test fun collisionPreservesCreditAndMatchesUnicodeAndCase() {
        val file = mediaName("Café", "", "mp3", "Àna", "", "")
        assertEquals("Café (3) [@Àna].mp3", file.available(setOf("CAFE\u0301 [@ÀNA].MP3", "Café (2) [@Àna].mp3")))
    }

    @Test fun namesFitAndroidByteLimitWithoutSplittingEmoji() {
        val name = mediaName("🎬".repeat(150), "", "mkv", "á".repeat(65), "", "").candidate(15)
        assertTrue(name.toByteArray(Charsets.UTF_8).size <= 200)
        assertFalse(name.contains('\uFFFD'))
        assertTrue(name.endsWith(" (15) [@${"á".repeat(32)}].mkv"))
    }

    @Test fun sharedTextAndInputRejectUnexpectedSchemesAndCredentials() {
        assertEquals("https://example.com/a?b=c", sharedLink("Veja https://example.com/a?b=c."))
        assertNull(validLink("file:///data/media.mp4"))
        assertNull(validLink("https://user:secret@example.com"))
        assertNull(validLink("--exec"))
    }

    @Test fun recoveredQueueNeverTreatsAnInterruptedTransferAsComplete() {
        assertEquals(State.PAUSED, State.RUNNING.recovered())
        assertEquals(State.PAUSED, State.SAVING.recovered())
        assertEquals(State.QUEUED, State.QUEUED.recovered())
        assertEquals(State.DONE, State.DONE.recovered())
        assertTrue(State.CANCELLED.canRetry)
        assertFalse(State.DONE.canRetry)
    }

    @Test fun qualityCapIsAppliedToCombinedAndSplitVideo() {
        assertEquals("bestvideo[height<=720]+bestaudio/best[height<=720]", Quality.HD720.format())
        assertEquals("bestaudio/best", Quality.MP3.format())
    }
}
