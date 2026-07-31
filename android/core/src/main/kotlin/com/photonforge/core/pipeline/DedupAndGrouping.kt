package com.photonforge.core.pipeline

import com.photonforge.core.GrayImage
import com.photonforge.core.cv.ImageOps

/**
 * dHash + session grouping ports (photo_workflow.dedup / grouping).
 *
 * Hash note: the desktop uses PIL/imagehash (Lanczos resample to 9x8); this
 * implementation uses bilinear resample, so hashes are self-consistent within
 * the app but may differ by a few bits from desktop-computed hashes on the same
 * frame. Dedup only ever compares hashes computed in a single run's session
 * window, so this does not affect correctness — recorded in the brief.
 */
object Dedup {

    const val DHASH_THRESHOLD = 2   // FR-1.3

    /** 64-bit dHash: resize gray to 9x8, compare horizontally adjacent pixels. */
    fun dhash(gray: GrayImage): Long {
        val small = ImageOps.resizeBilinear(gray, 9, 8)
        var result = 0L
        for (y in 0 until 8) {
            for (x in 0 until 8) {
                val bit = if (small[y, x] < small[y, x + 1]) 1L else 0L
                result = (result shl 1) or bit
            }
        }
        return result
    }

    fun hammingDistance(a: Long, b: Long): Int = java.lang.Long.bitCount(a xor b)

    /**
     * Within-session duplicate marking: first occurrence kept, later frames with
     * Hamming distance <= threshold flagged. Returns the set of duplicate keys.
     */
    fun markDuplicates(
        entries: List<Pair<String, Long>>,          // (key, hash) in shooting order
        sessionOf: (String) -> String,
        threshold: Int = DHASH_THRESHOLD,
    ): Set<String> {
        val seen = HashMap<String, MutableList<Long>>()
        val duplicates = HashSet<String>()
        for ((key, hash) in entries) {
            val session = seen.getOrPut(sessionOf(key)) { mutableListOf() }
            val isDup = session.any { hammingDistance(it, hash) <= threshold }
            if (isDup) duplicates.add(key) else session.add(hash)
        }
        return duplicates
    }
}

object Grouping {

    const val SESSION_GAP_MINUTES = 30L   // FR-1.2

    /**
     * Assign session ids by temporal proximity (photo_workflow.grouping).
     * timestamps: key -> epoch millis, or null for untimed (-> session_0000).
     */
    fun clusterSessions(timestamps: Map<String, Long?>): Map<String, String> {
        val timed = timestamps.entries.filter { it.value != null }
            .map { it.key to it.value!! }
            .sortedBy { it.second }
        val out = HashMap<String, String>()
        var sessionIdx = 0
        var prev: Long? = null
        val gapMs = SESSION_GAP_MINUTES * 60_000
        for ((key, t) in timed) {
            if (prev == null || t - prev > gapMs) sessionIdx++
            out[key] = "session_%04d".format(sessionIdx)
            prev = t
        }
        for ((key, t) in timestamps) if (t == null) out[key] = "session_0000"
        return out
    }
}
