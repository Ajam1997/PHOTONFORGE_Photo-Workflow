package com.photonforge.core.genre

import com.photonforge.core.GenreResult
import kotlin.math.exp

/**
 * Port of photo_workflow.genre_router route_genre — adapter path + CLIP-prototype
 * cosine fallback + EXIF motion-blur gate + top-2-margin review flag.
 *
 * Deliberate Phase 2 scope cut (documented in android-port-brief.md): the full
 * five-expert product-of-experts fallback (EXIF/YOLO/context/sharpness priors) is
 * NOT ported. The bundled training DB ships an active learned adapter for both
 * axes, which is the primary desktop path; without an adapter we fall back to the
 * CLIP prototype expert alone (fusion weight 4.0 of 8.0 on desktop — the dominant
 * signal). Full PoE parity is a Phase 3+ item if A/B shows it matters.
 */
object GenreRouter {

    val SUBJECTS = listOf(
        "people", "pet", "wildlife", "plant", "landscape", "seascape", "sky",
        "cityscape", "building", "vehicle", "food", "object", "abstract",
        "monument", "waterfall",
    )

    val PHOTO_TYPES = listOf(
        "portrait", "candid", "scenic", "street", "macro", "architecture",
        "action", "aerial", "motion-blur", "still-life", "documentary",
    )

    const val REVIEW_MARGIN = 0.02
    const val MOTION_BLUR_SHUTTER_S = 0.5
    const val MOTION_BLUR_GATE_CONF = 0.80
    const val CLIP_TEMPERATURE = 0.35

    class LinearHead(
        val classes: List<String>,
        val weight: Array<FloatArray>,   // (nClasses, dim)
        val bias: FloatArray,            // (nClasses)
    )

    class Adapter(val subject: LinearHead?, val type: LinearHead?)

    /** Prototype matrix: first SUBJECTS.size rows are subjects, rest are types. */
    class Prototypes(val rows: Array<FloatArray>)

    fun softmax(z: DoubleArray): DoubleArray {
        val mx = z.max()
        val e = DoubleArray(z.size) { exp(z[it] - mx) }
        val s = e.sum()
        return DoubleArray(z.size) { e[it] / s }
    }

    /** genre_adapter.predict_axis: softmax(W @ e + b); unseen classes -> 0.0. */
    fun predictAxis(embedding: FloatArray, head: LinearHead, axisLabels: List<String>): Map<String, Double> {
        val logits = DoubleArray(head.classes.size) { i ->
            var s = head.bias[i].toDouble()
            val row = head.weight[i]
            for (j in embedding.indices) s += row[j].toDouble() * embedding[j]
            s
        }
        val probs = softmax(logits)
        val pmap = head.classes.indices.associate { head.classes[it] to probs[it] }
        return axisLabels.associateWith { pmap[it] ?: 0.0 }
    }

    /** _compute_clip_similarity_axis: cosine to prototypes, temperature softmax. */
    fun clipSimilarityAxis(
        embedding: FloatArray,
        prototypes: Array<FloatArray>?,
        axisLabels: List<String>,
    ): Map<String, Double> {
        if (prototypes == null || embedding.all { it == 0f }) {
            return axisLabels.associateWith { 1.0 / axisLabels.size }
        }
        val sims = DoubleArray(axisLabels.size) { i ->
            var s = 0.0
            val row = prototypes[i]
            for (j in embedding.indices) s += row[j].toDouble() * embedding[j]
            s
        }
        val mx = sims.max()
        val e = DoubleArray(sims.size) { exp((sims[it] - mx) / CLIP_TEMPERATURE) }
        val total = e.sum()
        return axisLabels.mapIndexed { i, l -> l to e[i] / total }.toMap()
    }

    fun applyMotionBlurGate(typeDist: Map<String, Double>, shutterSeconds: Double?): Map<String, Double> {
        if (shutterSeconds == null || shutterSeconds < MOTION_BLUR_SHUTTER_S) return typeDist
        val current = typeDist["motion-blur"] ?: 0.0
        if (current >= MOTION_BLUR_GATE_CONF) return typeDist
        val remaining = 1.0 - MOTION_BLUR_GATE_CONF
        val othersTotal = typeDist.entries.filter { it.key != "motion-blur" }.sumOf { it.value }
        return typeDist.mapValues { (k, v) ->
            when {
                k == "motion-blur" -> MOTION_BLUR_GATE_CONF
                othersTotal > 0 -> v / othersTotal * remaining
                else -> remaining / maxOf(typeDist.size - 1, 1)
            }
        }
    }

    fun top2Margin(dist: Map<String, Double>): Double {
        if (dist.size < 2) return 1.0
        val sorted = dist.values.sortedDescending()
        return sorted[0] - sorted[1]
    }

    fun route(
        clipEmbedding: FloatArray?,
        adapter: Adapter?,
        prototypes: Prototypes?,
        shutterSeconds: Double? = null,
    ): GenreResult {
        val haveClip = clipEmbedding != null && clipEmbedding.any { it != 0f }
        val useAdapter = adapter?.subject != null && adapter.type != null && haveClip

        val subjDist: Map<String, Double>
        var typeDist: Map<String, Double>
        if (useAdapter) {
            subjDist = predictAxis(clipEmbedding!!, adapter!!.subject!!, SUBJECTS)
            typeDist = predictAxis(clipEmbedding, adapter.type!!, PHOTO_TYPES)
        } else {
            var subjectProtos: Array<FloatArray>? = null
            var typeProtos: Array<FloatArray>? = null
            if (prototypes != null && prototypes.rows.size >= SUBJECTS.size + PHOTO_TYPES.size) {
                subjectProtos = prototypes.rows.copyOfRange(0, SUBJECTS.size)
                typeProtos = prototypes.rows.copyOfRange(SUBJECTS.size, SUBJECTS.size + PHOTO_TYPES.size)
            }
            val emb = clipEmbedding ?: FloatArray(512)
            subjDist = clipSimilarityAxis(emb, subjectProtos, SUBJECTS)
            typeDist = clipSimilarityAxis(emb, typeProtos, PHOTO_TYPES)
        }

        typeDist = applyMotionBlurGate(typeDist, shutterSeconds)

        val subject = subjDist.maxByOrNull { it.value }!!.key
        val photoType = typeDist.maxByOrNull { it.value }!!.key
        val needsReview = top2Margin(subjDist) < REVIEW_MARGIN || top2Margin(typeDist) < REVIEW_MARGIN

        return GenreResult(
            subject = subject,
            subjectConfidence = Math.round(subjDist.getValue(subject) * 10000.0) / 10000.0,
            photoType = photoType,
            typeConfidence = Math.round(typeDist.getValue(photoType) * 10000.0) / 10000.0,
            subjectDistribution = subjDist,
            typeDistribution = typeDist,
            needsReview = needsReview,
        )
    }
}
