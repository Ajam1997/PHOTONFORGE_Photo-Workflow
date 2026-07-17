package com.photonforge.core.cv

import com.photonforge.core.ExposureScores
import com.photonforge.core.FaceDetection
import com.photonforge.core.RgbImage
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min

/** Port of photo_workflow.exposure (FR-1.6): 11-zone histogram, clipping, DR, style. */
object Exposure {

    const val NUM_ZONES = 11

    private fun log2(x: Double): Double = ln(x) / ln(2.0)

    fun detectStyle(zoneProbs: DoubleArray): Pair<String, Double> {
        var high = 0.0
        for (i in 7 until NUM_ZONES) high += zoneProbs[i]
        var low = 0.0
        for (i in 0 until 5) low += zoneProbs[i]

        if (high > 0.70 && low < 0.10) return "high_key" to high
        if (low > 0.70 && high < 0.10) {
            var accent = 0.0
            for (i in 8 until NUM_ZONES) accent += zoneProbs[i]
            return if (accent > 0.02) "low_key" to low else "low_key" to low * 0.7
        }
        val shadowPeak = zoneProbs[0] + zoneProbs[1]
        var highlightPeak = 0.0
        for (i in 8 until NUM_ZONES) highlightPeak += zoneProbs[i]
        if (shadowPeak > 0.25 && highlightPeak > 0.25) {
            return "silhouette" to min(shadowPeak, highlightPeak)
        }
        return "normal" to 0.0
    }

    fun faceExposure(img: RgbImage, faces: List<FaceDetection>): Double {
        if (faces.isEmpty()) return -1.0
        val face = faces.maxByOrNull { it.confidence }!!
        var x = max(0, face.bbox[0])
        var y = max(0, face.bbox[1])
        val x2 = min(img.width, face.bbox[0] + face.bbox[2])
        val y2 = min(img.height, face.bbox[1] + face.bbox[3])
        if (x2 <= x || y2 <= y) return -1.0

        // Median luma of the face region (YCrCb Y == BGR2GRAY weights).
        val vals = FloatArray((x2 - x) * (y2 - y))
        var i = 0
        for (yy in y until y2) {
            for (xx in x until x2) {
                vals[i++] = Math.round(
                    0.299f * img.r(yy, xx) + 0.587f * img.g(yy, xx) + 0.114f * img.b(yy, xx)
                ).toFloat()
            }
        }
        vals.sort()
        val n = vals.size
        val median = if (n % 2 == 1) vals[n / 2].toDouble()
        else (vals[n / 2 - 1] + vals[n / 2]) / 2.0

        val idealLow = 110.0
        val idealHigh = 220.0
        return when {
            median in idealLow..idealHigh -> 1.0
            median < idealLow -> max(0.0, median / idealLow)
            else -> max(0.0, 1.0 - (median - idealHigh) / (255.0 - idealHigh))
        }
    }

    fun score(img: RgbImage, faces: List<FaceDetection> = emptyList()): ExposureScores {
        val n = img.width * img.height
        val luma = FloatArray(n)
        for (i in 0 until n) {
            val r = img.pixels[i * 3].toInt() and 0xFF
            val g = img.pixels[i * 3 + 1].toInt() and 0xFF
            val b = img.pixels[i * 3 + 2].toInt() and 0xFF
            // Round to uint8 like cv2's YCrCb conversion — the zone histogram
            // and clipping thresholds are calibrated against integer luma.
            luma[i] = Math.round(0.299f * r + 0.587f * g + 0.114f * b).toFloat()
        }

        // np.histogram(luma, bins=11, range=(0,256))
        val hist = DoubleArray(NUM_ZONES)
        for (v in luma) {
            var bin = (v * NUM_ZONES / 256f).toInt()
            if (bin >= NUM_ZONES) bin = NUM_ZONES - 1
            if (bin < 0) bin = 0
            hist[bin]++
        }
        val totalPixels = n.toDouble()

        var entropy = 0.0
        var nzSum = 0.0
        for (h in hist) if (h > 0) nzSum += h
        if (nzSum > 0) {
            for (h in hist) {
                if (h > 0) {
                    val p = h / nzSum
                    entropy -= p * log2(p)
                }
            }
        }
        val zoneEntropy = if (nzSum > 0) entropy / log2(NUM_ZONES.toDouble()) else 0.0

        var zoneDiversity = 0
        for (h in hist) if (h > totalPixels * 0.01) zoneDiversity++

        var shadows = 0L
        var highlights = 0L
        for (v in luma) {
            if (v < 4.0f) shadows++
            if (v > 251.0f) highlights++
        }
        val clippingShadows = shadows / totalPixels
        val clippingHighlights = highlights / totalPixels

        val p005 = ImageOps.percentile(luma, 0.5)
        val p995 = ImageOps.percentile(luma, 99.5)
        val dynamicRange = (p995 - p005) / 255.0

        var midtones = 0L
        for (v in luma) if (v in 90.0f..160.0f) midtones++
        val midtoneDensity = midtones / max(totalPixels, 1.0)

        val zoneProbs = DoubleArray(NUM_ZONES) { hist[it] / max(totalPixels, 1.0) }
        val (style, styleConfidence) = detectStyle(zoneProbs)

        val face = faceExposure(img, faces)

        var score = zoneEntropy
        if (style != "silhouette") score -= clippingShadows * 2.0
        if (style != "high_key") score -= clippingHighlights * 2.0
        if (style == "normal") score += (dynamicRange - 0.5) * 0.3
        if (face >= 0 && face < 0.5) score -= (0.5 - face) * 0.4
        val overall = max(0.0, min(1.0, score))

        return ExposureScores(
            zoneEntropy = round4(zoneEntropy),
            zoneDiversity = zoneDiversity,
            clippingShadows = round4(clippingShadows),
            clippingHighlights = round4(clippingHighlights),
            dynamicRange = round4(dynamicRange),
            midtoneDensity = round4(midtoneDensity),
            faceExposure = round4(face),
            style = style,
            styleConfidence = round4(styleConfidence),
            overall = round4(overall),
        )
    }
}
