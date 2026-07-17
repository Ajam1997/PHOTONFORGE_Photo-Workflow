package com.photonforge.core.cv

import com.photonforge.core.FaceDetection
import com.photonforge.core.GrayImage
import com.photonforge.core.Mask
import com.photonforge.core.ObjectDetection
import com.photonforge.core.SharpnessScores
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/** Port of photo_workflow.sharpness (FR-1.4): Tenengrad + SML, subject-aware regions. */
object Sharpness {

    const val SHARP_THRESHOLD = 0.25
    const val MOTION_ANISOTROPY_THRESHOLD = 2.5

    private val ANIMAL_EYE_CLASSES = setOf("cat", "dog", "bird", "horse", "bear")

    class FocusMaps(val ten: FloatArray, val ml: FloatArray, val gx: FloatArray, val gy: FloatArray)

    fun focusMaps(gray: GrayImage): FocusMaps {
        val gx = ImageOps.sobelX(gray)
        val gy = ImageOps.sobelY(gray)
        val ten = FloatArray(gx.size)
        for (i in gx.indices) ten[i] = gx[i] * gx[i] + gy[i] * gy[i]
        val lxx = ImageOps.sobelXX(gray)
        val lyy = ImageOps.sobelYY(gray)
        val ml = FloatArray(lxx.size)
        for (i in lxx.indices) ml[i] = abs(lxx[i]) + abs(lyy[i])
        return FocusMaps(ten, ml, gx, gy)
    }

    private fun maskedMean(map: FloatArray, mask: Mask): Double {
        var s = 0.0
        var n = 0L
        for (i in map.indices) {
            if (mask.data[i].toInt() != 0) { s += map[i]; n++ }
        }
        return if (n > 0) s / n else 0.0
    }

    fun regionScoreFromMaps(maps: FocusMaps, gray: GrayImage, mask: Mask): Double {
        if (mask.sum() == 0L) return 0.0

        var region = ImageOps.erode3(mask)
        if (region.sum() == 0L) region = mask

        val ten = maskedMean(maps.ten, region)
        val smlVal = maskedMean(maps.ml, region)
        val raw: Double
        if (ten <= 0.0 && smlVal <= 0.0) {
            val lap = ImageOps.laplacian(gray)
            var s = 0.0
            var n = 0L
            for (i in lap.indices) if (region.data[i].toInt() != 0) { s += abs(lap[i]); n++ }
            val rawLap = if (n > 0) s / n else 0.0
            if (rawLap <= 0.0) return 0.0
            raw = rawLap
        } else if (ten <= 0.0 || smlVal <= 0.0) {
            raw = max(ten, smlVal)
        } else {
            raw = sqrt(ten * smlVal)
        }

        var lumaSum = 0.0
        var lumaN = 0L
        for (i in gray.pixels.indices) {
            if (mask.data[i].toInt() != 0) { lumaSum += gray.pixels[i]; lumaN++ }
        }
        val meanLuma = if (lumaN > 0) lumaSum / lumaN else 0.0
        val lumaFactor = max(meanLuma, 1.0) / 128.0
        return min(raw / (500.0 * lumaFactor), 1.0)
    }

    fun gradientAnisotropy(gx: FloatArray, gy: FloatArray, mask: Mask): Double {
        var ex = 0.0
        var ey = 0.0
        var n = 0L
        for (i in gx.indices) {
            if (mask.data[i].toInt() != 0) {
                ex += gx[i].toDouble() * gx[i]
                ey += gy[i].toDouble() * gy[i]
                n++
            }
        }
        if (n == 0L) return 1.0
        ex /= n
        ey /= n
        val lo = min(ex, ey)
        if (lo <= 0.0) return 1.0
        return max(ex, ey) / lo
    }

    fun classifyBlur(subjectSharp: Boolean, bgSharp: Boolean, anisotropy: Double): String = when {
        subjectSharp && bgSharp -> "sharp"
        subjectSharp && !bgSharp -> "bokeh"
        !subjectSharp && bgSharp ->
            if (anisotropy >= MOTION_ANISOTROPY_THRESHOLD) "motion_subject" else "misfocused"
        else -> "motion_global"
    }

    fun score(
        gray: GrayImage,
        mask: Mask,
        faces: List<FaceDetection> = emptyList(),
        detections: List<ObjectDetection> = emptyList(),
    ): SharpnessScores {
        val maps = focusMaps(gray)
        val invMask = mask.inverted()
        val subjectScore = regionScoreFromMaps(maps, gray, mask)
        val backgroundScore = regionScoreFromMaps(maps, gray, invMask)

        var eyeScore = subjectScore
        val face = faces.firstOrNull()
        if (face != null && face.landmarks.containsKey("left_eye") && face.landmarks.containsKey("right_eye")) {
            val le = face.landmarks.getValue("left_eye")
            val re = face.landmarks.getValue("right_eye")
            val eyeW = abs(re[0] - le[0])
            val eyeH = max(eyeW / 3, 10)
            val yCenter = (le[1] + re[1]) / 2
            var xMin = min(le[0], re[0]) - eyeW / 4
            var xMax = max(le[0], re[0]) + eyeW / 4
            var yMin = yCenter - eyeH
            var yMax = yCenter + eyeH
            yMin = max(0, yMin); yMax = min(gray.height, yMax)
            xMin = max(0, xMin); xMax = min(gray.width, xMax)
            if (yMax > yMin && xMax > xMin) {
                eyeScore = regionScoreFromMaps(maps, gray, rectMask(gray, xMin, yMin, xMax, yMax))
            }
        } else if (faces.isEmpty() && detections.isNotEmpty()) {
            for (det in detections) {
                if (det.className in ANIMAL_EYE_CLASSES) {
                    val (x, y, w, h) = listOf(det.bbox[0], det.bbox[1], det.bbox[2], det.bbox[3])
                    val headH = h / 3
                    val yMin = max(0, y)
                    val yMax = min(gray.height, y + headH)
                    val xMin = max(0, x)
                    val xMax = min(gray.width, x + w)
                    if (yMax > yMin && xMax > xMin) {
                        eyeScore = regionScoreFromMaps(maps, gray, rectMask(gray, xMin, yMin, xMax, yMax))
                    }
                    break
                }
            }
        }

        val sharpnessContrast = subjectScore / max(backgroundScore, 0.01)
        val anisotropy = gradientAnisotropy(maps.gx, maps.gy, mask)
        val blurType = classifyBlur(
            subjectScore >= SHARP_THRESHOLD,
            backgroundScore >= SHARP_THRESHOLD,
            anisotropy,
        )
        var overall = 0.5 * subjectScore + 0.35 * eyeScore + 0.15 * min(sharpnessContrast / 5.0, 1.0)
        overall = min(overall, 1.0)

        return SharpnessScores(
            subject = round4(subjectScore),
            eyeRegion = round4(eyeScore),
            background = round4(backgroundScore),
            sharpnessContrast = round4(sharpnessContrast),
            blurType = blurType,
            overall = round4(overall),
        )
    }

    private fun rectMask(gray: GrayImage, xMin: Int, yMin: Int, xMax: Int, yMax: Int): Mask {
        val data = ByteArray(gray.width * gray.height)
        for (y in yMin until yMax) {
            for (x in xMin until xMax) data[y * gray.width + x] = 1
        }
        return Mask(gray.width, gray.height, data)
    }
}

internal fun round4(v: Double): Double = Math.round(v * 10000.0) / 10000.0
