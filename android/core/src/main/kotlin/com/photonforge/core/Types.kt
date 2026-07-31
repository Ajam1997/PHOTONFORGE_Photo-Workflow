package com.photonforge.core

/** Grayscale image, float pixels in 0..255 (matches numpy uint8 promoted to float). */
class GrayImage(val width: Int, val height: Int, val pixels: FloatArray) {
    init { require(pixels.size == width * height) }
    operator fun get(y: Int, x: Int): Float = pixels[y * width + x]
    operator fun set(y: Int, x: Int, v: Float) { pixels[y * width + x] = v }
}

/** Interleaved RGB image, 0..255 per channel (byte order R,G,B). */
class RgbImage(val width: Int, val height: Int, val pixels: ByteArray) {
    init { require(pixels.size == width * height * 3) }
    fun r(y: Int, x: Int): Int = pixels[(y * width + x) * 3].toInt() and 0xFF
    fun g(y: Int, x: Int): Int = pixels[(y * width + x) * 3 + 1].toInt() and 0xFF
    fun b(y: Int, x: Int): Int = pixels[(y * width + x) * 3 + 2].toInt() and 0xFF

    /** Luma per OpenCV BGR2GRAY / BGR2YCrCb Y: 0.299R + 0.587G + 0.114B. */
    fun toGray(): GrayImage {
        val out = FloatArray(width * height)
        for (i in 0 until width * height) {
            val r = pixels[i * 3].toInt() and 0xFF
            val g = pixels[i * 3 + 1].toInt() and 0xFF
            val b = pixels[i * 3 + 2].toInt() and 0xFF
            out[i] = (0.299f * r + 0.587f * g + 0.114f * b)
        }
        return GrayImage(width, height, out)
    }
}

/** Binary mask: 1 = subject, 0 = background. */
class Mask(val width: Int, val height: Int, val data: ByteArray) {
    init { require(data.size == width * height) }
    operator fun get(y: Int, x: Int): Int = data[y * width + x].toInt()
    fun sum(): Long { var s = 0L; for (b in data) s += b; return s }
    fun inverted(): Mask {
        val out = ByteArray(data.size)
        for (i in data.indices) out[i] = (1 - data[i]).toByte()
        return Mask(width, height, out)
    }
    companion object {
        fun full(width: Int, height: Int): Mask =
            Mask(width, height, ByteArray(width * height) { 1 })
    }
}

data class FaceDetection(
    val bbox: IntArray,                       // x, y, w, h
    val confidence: Float,
    val landmarks: Map<String, IntArray>,     // left_eye/right_eye/... -> [x, y]
)

data class ObjectDetection(
    val bbox: IntArray,                       // x, y, w, h
    val confidence: Float,
    val classId: Int,
    val className: String,
)

data class SharpnessScores(
    val subject: Double,
    val eyeRegion: Double,
    val background: Double,
    val sharpnessContrast: Double,
    val blurType: String,                     // sharp|bokeh|motion_subject|motion_global|misfocused
    val overall: Double,
)

data class CompositionScores(
    val ruleOfThirds: Double,
    val symmetry: Double,
    val leadingLines: Double,
    val negativeSpace: Double,
    val subjectIsolation: Double,
    val balance: Double,
    val overall: Double,
    val colorfulness: Double,
)

data class ExposureScores(
    val zoneEntropy: Double,
    val zoneDiversity: Int,
    val clippingShadows: Double,
    val clippingHighlights: Double,
    val dynamicRange: Double,
    val midtoneDensity: Double,
    val faceExposure: Double,                 // -1.0 when no face
    val style: String,                        // normal|high_key|low_key|silhouette
    val styleConfidence: Double,
    val overall: Double,
)

data class GenreResult(
    val subject: String,
    val subjectConfidence: Double,
    val photoType: String,
    val typeConfidence: Double,
    val subjectDistribution: Map<String, Double>,
    val typeDistribution: Map<String, Double>,
    val needsReview: Boolean,
)

data class FusionResult(
    val masterScore: Double,
    val subject: String,
    val subjectConfidence: Double,
    val photoType: String,
    val typeConfidence: Double,
    val subScores: Map<String, Double>,
    val hardReject: Boolean,
    val hardRejectReason: String,
    val starRating: Int,
    val colorLabel: Int,
    val needsReview: Boolean,
)
