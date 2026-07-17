package com.photonforge.core.fusion

import com.photonforge.core.CompositionScores
import com.photonforge.core.ExposureScores
import com.photonforge.core.FaceDetection
import com.photonforge.core.FusionResult
import com.photonforge.core.GenreResult
import com.photonforge.core.GrayImage
import com.photonforge.core.SharpnessScores
import com.photonforge.core.genre.GenreRouter
import kotlin.math.max
import kotlin.math.min

/** Port of photo_workflow.score_fusion: two-axis weighted fusion + rating. */
object ScoreFusion {

    // Darktable color label constants (purple reserved for the user; never auto-set).
    const val DT_RED = 0
    const val DT_YELLOW = 1
    const val DT_GREEN = 2
    const val DT_BLUE = 3
    const val DT_NONE = -1

    const val RATING_ABS_FLOOR = 0.25
    const val EYES_CLOSED_THRESHOLD = 0.15
    private const val EYE_ROI_RADIUS = 10
    private const val OPEN_EYE_VARIANCE_THRESHOLD = 400.0

    val TECHNICAL_KEYS = setOf(
        "eye_sharpness", "subject_sharpness", "sharpness_contrast", "front_to_back_sharp",
        "exposure_overall", "dynamic_range", "zone_entropy", "highlight_clip", "face_exposure",
        "blur_type_penalty", "motion_tolerance",
    )

    /** {'subject': {label: {key: w}}, 'type': {label: {key: w}}}. */
    class WeightProfiles(
        val subject: Map<String, Map<String, Double>>,
        val type: Map<String, Map<String, Double>>,
    )

    fun estimateEyeOpenness(face: FaceDetection, gray: GrayImage): Double {
        val variances = ArrayList<Double>(2)
        for (key in listOf("left_eye", "right_eye")) {
            val pt = face.landmarks[key] ?: continue
            val cx = pt[0]
            val cy = pt[1]
            val y0 = max(0, cy - EYE_ROI_RADIUS)
            val y1 = min(gray.height, cy + EYE_ROI_RADIUS)
            val x0 = max(0, cx - EYE_ROI_RADIUS)
            val x1 = min(gray.width, cx + EYE_ROI_RADIUS)
            if (y1 <= y0 || x1 <= x0) continue
            var s = 0.0
            var n = 0
            for (y in y0 until y1) for (x in x0 until x1) { s += gray[y, x]; n++ }
            val mean = s / n
            var v = 0.0
            for (y in y0 until y1) for (x in x0 until x1) {
                val d = gray[y, x] - mean
                v += d * d
            }
            variances.add(v / n)
        }
        if (variances.isEmpty()) return 0.5
        return variances.sumOf { min(it / OPEN_EYE_VARIANCE_THRESHOLD, 1.0) } / variances.size
    }

    fun buildSubScoreDict(
        sharpness: SharpnessScores,
        composition: CompositionScores,
        exposure: ExposureScores,
        aesthetic: Double?,
        faces: List<FaceDetection> = emptyList(),
        gray: GrayImage? = null,
    ): MutableMap<String, Double> {
        val scores = mutableMapOf(
            "eye_sharpness" to sharpness.eyeRegion,
            "subject_sharpness" to sharpness.subject,
            "sharpness_contrast" to min(sharpness.sharpnessContrast / 5.0, 1.0),
            "composition_rot" to composition.ruleOfThirds,
            "symmetry" to composition.symmetry,
            "leading_lines" to composition.leadingLines,
            "negative_space" to composition.negativeSpace,
            "subject_isolation" to composition.subjectIsolation,
            "balance" to composition.balance,
            "zone_entropy" to exposure.zoneEntropy,
            "dynamic_range" to exposure.dynamicRange,
            "exposure_overall" to exposure.overall,
            "aesthetic_clip" to (aesthetic ?: 0.0),
        )
        scores["face_exposure"] = if (exposure.faceExposure >= 0) exposure.faceExposure else 0.5
        scores["front_to_back_sharp"] = min(sharpness.subject, sharpness.background)
        scores["blur_type_penalty"] =
            if (sharpness.blurType in setOf("motion_global", "misfocused")) 0.0 else 1.0
        scores["blur_type_bonus"] = when (sharpness.blurType) {
            "bokeh" -> 1.0
            "sharp" -> 0.5
            else -> 0.0
        }
        scores["motion_tolerance"] = if (sharpness.blurType == "motion_global") 0.0 else 1.0
        scores["highlight_clip"] = 1.0 - exposure.clippingHighlights
        scores["expression_proxy"] = if (faces.isNotEmpty() && gray != null) {
            faces.maxOf { estimateEyeOpenness(it, gray) }
        } else 0.5
        scores["behavior_proxy"] = if (sharpness.blurType == "motion_subject") 1.0 else 0.5
        scores["color_contrast"] = composition.colorfulness
        return scores
    }

    fun computeMasterScore(
        subScores: Map<String, Double>,
        genre: GenreResult,
        profiles: WeightProfiles,
        dropKeys: Set<String> = emptySet(),
    ): Double {
        val subjectW = profiles.subject
        val typeW = profiles.type
        val subj = when {
            genre.subject in subjectW -> genre.subject
            GenreRouter.SUBJECTS[0] in subjectW -> GenreRouter.SUBJECTS[0]
            else -> subjectW.keys.first()
        }
        val ptype = when {
            genre.photoType in typeW -> genre.photoType
            GenreRouter.PHOTO_TYPES[0] in typeW -> GenreRouter.PHOTO_TYPES[0]
            else -> typeW.keys.first()
        }

        val effective = HashMap<String, Double>()
        for ((key, w) in subjectW.getValue(subj)) effective[key] = (effective[key] ?: 0.0) + 0.5 * w
        for ((key, w) in typeW.getValue(ptype)) effective[key] = (effective[key] ?: 0.0) + 0.5 * w
        for (k in dropKeys) effective.remove(k)

        var techNum = 0.0; var techDen = 0.0; var aesNum = 0.0; var aesDen = 0.0
        for ((key, weight) in effective) {
            val v = subScores[key] ?: continue
            if (key in TECHNICAL_KEYS) { techNum += weight * v; techDen += weight }
            else { aesNum += weight * v; aesDen += weight }
        }
        val technical = if (techDen > 0) techNum / techDen else null
        val aesthetic = if (aesDen > 0) aesNum / aesDen else null
        val master = when {
            technical == null && aesthetic == null -> return 0.0
            technical == null -> aesthetic!!
            aesthetic == null -> technical
            else -> min(technical, aesthetic)
        }
        return max(0.0, min(1.0, master))
    }

    fun checkHardGates(
        sharpness: SharpnessScores,
        faces: List<FaceDetection> = emptyList(),
        gray: GrayImage? = null,
    ): Pair<Boolean, String> {
        if (sharpness.blurType == "motion_global" && sharpness.subject < 0.2) {
            return true to "motion_global_blur"
        }
        if (sharpness.blurType == "misfocused" && sharpness.eyeRegion < 0.15) {
            return true to "misfocused"
        }
        if (faces.isNotEmpty() && gray != null &&
            faces.all { estimateEyeOpenness(it, gray) < EYES_CLOSED_THRESHOLD }
        ) {
            return true to "all_eyes_closed"
        }
        return false to ""
    }

    fun starsToColorLabel(stars: Int, hardReject: Boolean = false): Int = when {
        hardReject -> DT_NONE
        stars >= 5 -> DT_BLUE
        stars >= 4 -> DT_GREEN
        stars <= 1 -> DT_YELLOW
        else -> DT_NONE
    }

    fun absoluteStar(master: Double, hardReject: Boolean = false): Int = when {
        hardReject || master < RATING_ABS_FLOOR -> 1
        master < 0.40 -> 2
        master < 0.50 -> 3
        master < 0.60 -> 4
        else -> 5
    }

    /** keptSorted: ascending master scores of the shoot's kept frames (>= floor). */
    fun hybridStar(master: Double, hardReject: Boolean, keptSorted: List<Double>): Int {
        if (hardReject || master < RATING_ABS_FLOOR) return 1
        val k = keptSorted.size
        if (k <= 1) return 3
        // bisect_left
        var lo = 0
        var hi = k
        while (lo < hi) {
            val mid = (lo + hi) / 2
            if (keptSorted[mid] < master) lo = mid + 1 else hi = mid
        }
        val pct = lo.toDouble() / (k - 1)
        return when {
            pct >= 0.90 -> 5
            pct >= 0.70 -> 4
            pct >= 0.40 -> 3
            else -> 2
        }
    }

    private fun scoreToStars(master: Double): Int =
        max(1, min(5, Math.round(master * 5).toInt()))

    private fun scoreToColorLabel(master: Double, hardReject: Boolean): Int = when {
        hardReject -> DT_NONE
        master < 0.3 -> DT_YELLOW
        master < 0.5 -> DT_NONE
        master < 0.75 -> DT_GREEN
        else -> DT_BLUE
    }

    fun fuse(
        sharpness: SharpnessScores,
        composition: CompositionScores,
        exposure: ExposureScores,
        genre: GenreResult,
        aesthetic: Double?,
        faces: List<FaceDetection> = emptyList(),
        gray: GrayImage? = null,
        profiles: WeightProfiles,
    ): FusionResult {
        val subScores = buildSubScoreDict(sharpness, composition, exposure, aesthetic, faces, gray)
        val (hardReject, reason) = checkHardGates(sharpness, faces, gray)

        val drop = mutableSetOf<String>()
        if (aesthetic == null) drop.add("aesthetic_clip")
        if (faces.isEmpty()) { drop.add("face_exposure"); drop.add("expression_proxy") }
        if (sharpness.blurType != "motion_subject") drop.add("behavior_proxy")

        val master = computeMasterScore(subScores, genre, profiles, drop)
        return FusionResult(
            masterScore = Math.round(master * 10000.0) / 10000.0,
            subject = genre.subject,
            subjectConfidence = Math.round(genre.subjectConfidence * 10000.0) / 10000.0,
            photoType = genre.photoType,
            typeConfidence = Math.round(genre.typeConfidence * 10000.0) / 10000.0,
            subScores = subScores,
            hardReject = hardReject,
            hardRejectReason = reason,
            starRating = scoreToStars(master),
            colorLabel = scoreToColorLabel(master, hardReject),
            needsReview = genre.needsReview,
        )
    }
}
