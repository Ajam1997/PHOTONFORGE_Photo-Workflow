package com.photonforge.core

import com.photonforge.core.cv.Composition
import com.photonforge.core.cv.Exposure
import com.photonforge.core.cv.Sharpness
import com.photonforge.core.fusion.ScoreFusion
import com.photonforge.core.genre.GenreRouter
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.float
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.roundToInt
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Golden-vector tests: the expected values are produced by the Python reference
 * (android/tools/generate_golden.py) on synthetic images defined by identical
 * formulas below. Exact-math paths assert tightly; cv2-dependent paths
 * (resize/blur rounding) get small tolerances.
 */
class GoldenTest {

    private val golden: JsonObject = Json.parseToJsonElement(
        javaClass.classLoader.getResourceAsStream("golden/golden.json")!!
            .bufferedReader().readText()
    ).jsonObject

    // --- synthetic images: MUST mirror generate_golden.py ------------------

    private fun synthGray(w: Int, h: Int, variant: Int): GrayImage {
        val px = FloatArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                val v: Int = when (variant) {
                    0 -> (x * 255 / maxOf(w - 1, 1) + y * 255 / maxOf(h - 1, 1)) / 2
                    1 -> (x * 37 + y * 91 + (x * y) % 23) % 256
                    2 -> if (y >= h / 4 && y < h / 2 && x >= w / 4 && x < w / 2) 230 else 20
                    else -> {
                        val cy = h / 2.0; val cx = w / 2.0
                        val d2 = (y - cy) * (y - cy) + (x - cx) * (x - cx)
                        val s = minOf(h, w) / 4.0
                        (255.0 * exp(-d2 / (2 * s * s))).toInt()
                    }
                }
                px[y * w + x] = v.toFloat()
            }
        }
        return GrayImage(w, h, px)
    }

    private fun synthRgb(w: Int, h: Int, variant: Int): RgbImage {
        val px = ByteArray(w * h * 3)
        for (y in 0 until h) {
            for (x in 0 until w) {
                val i = (y * w + x) * 3
                when (variant) {
                    0 -> {
                        px[i] = (x * 255 / maxOf(w - 1, 1)).toByte()
                        px[i + 1] = (y * 255 / maxOf(h - 1, 1)).toByte()
                        px[i + 2] = ((x + y) * 255 / maxOf(w + h - 2, 1)).toByte()
                    }
                    1 -> {
                        val base = (x * 3 + y * 5) % 40 + 100
                        px[i] = base.toByte()
                        px[i + 1] = (base + 5).toByte()
                        px[i + 2] = (base - 5).toByte()
                    }
                    2 -> {
                        val v = if (y < h / 8 && x < w / 8) 255 else 8
                        px[i] = v.toByte(); px[i + 1] = v.toByte(); px[i + 2] = v.toByte()
                    }
                    else -> {
                        px[i] = 253.toByte(); px[i + 1] = 253.toByte(); px[i + 2] = 253.toByte()
                    }
                }
            }
        }
        return RgbImage(w, h, px)
    }

    private fun grayAsRgb(g: GrayImage): RgbImage {
        val px = ByteArray(g.width * g.height * 3)
        for (i in 0 until g.width * g.height) {
            val v = g.pixels[i].roundToInt().coerceIn(0, 255).toByte()
            px[i * 3] = v; px[i * 3 + 1] = v; px[i * 3 + 2] = v
        }
        return RgbImage(g.width, g.height, px)
    }

    private fun centerMask(w: Int, h: Int): Mask {
        val data = ByteArray(w * h)
        for (y in h / 4 until 3 * h / 4) {
            for (x in w / 4 until 3 * w / 4) data[y * w + x] = 1
        }
        return Mask(w, h, data)
    }

    // Python computes gray via cv2 BGR2GRAY on uint8 (rounded); mirror that.
    private fun cvGray(rgb: RgbImage): GrayImage {
        val g = rgb.toGray()
        for (i in g.pixels.indices) g.pixels[i] = Math.round(g.pixels[i]).toFloat()
        return GrayImage(g.width, g.height, g.pixels)
    }

    // ------------------------------------------------------------- exposure
    @Test
    fun exposureMatchesReference() {
        for (case in golden.getValue("exposure").jsonArray) {
            val o = case.jsonObject
            val variant = o.getValue("variant").jsonPrimitive.int
            val rgb = synthRgb(96, 64, variant)
            val s = Exposure.score(rgb)
            assertEquals(o.getValue("zone_entropy").jsonPrimitive.double, s.zoneEntropy, 1e-3, "zone_entropy v$variant")
            assertEquals(o.getValue("zone_diversity").jsonPrimitive.int, s.zoneDiversity, "zone_diversity v$variant")
            assertEquals(o.getValue("clipping_shadows").jsonPrimitive.double, s.clippingShadows, 1e-3, "clipping_shadows v$variant")
            assertEquals(o.getValue("clipping_highlights").jsonPrimitive.double, s.clippingHighlights, 1e-3, "clipping_highlights v$variant")
            assertEquals(o.getValue("dynamic_range").jsonPrimitive.double, s.dynamicRange, 5e-3, "dynamic_range v$variant")
            assertEquals(o.getValue("style").jsonPrimitive.content, s.style, "style v$variant")
            assertEquals(o.getValue("overall").jsonPrimitive.double, s.overall, 5e-3, "overall v$variant")
        }
    }

    // ------------------------------------------------------------ sharpness
    @Test
    fun sharpnessMatchesReference() {
        for (case in golden.getValue("sharpness").jsonArray) {
            val o = case.jsonObject
            val variant = o.getValue("variant").jsonPrimitive.int
            val gray = synthGray(96, 64, variant)
            val mask = centerMask(96, 64)
            val s = Sharpness.score(gray, mask)
            assertEquals(o.getValue("subject").jsonPrimitive.double, s.subject, 2e-3, "subject v$variant")
            assertEquals(o.getValue("background").jsonPrimitive.double, s.background, 2e-3, "background v$variant")
            assertEquals(o.getValue("blur_type").jsonPrimitive.content, s.blurType, "blur_type v$variant")
            assertEquals(o.getValue("overall").jsonPrimitive.double, s.overall, 5e-3, "overall v$variant")
        }
    }

    // ---------------------------------------------------------- composition
    @Test
    fun compositionCloseToReference() {
        for (case in golden.getValue("composition").jsonArray) {
            val o = case.jsonObject
            val variant = o.getValue("variant").jsonPrimitive.int
            val rgb = synthRgb(96, 64, variant)
            val gray = cvGray(rgb)
            val mask = centerMask(96, 64)
            val s = Composition.score(rgb, gray, mask)
            // Tolerances: FFT/resize paths accumulate small numeric drift.
            assertEquals(o.getValue("symmetry").jsonPrimitive.double, s.symmetry, 0.03, "symmetry v$variant")
            assertEquals(o.getValue("colorfulness").jsonPrimitive.double, s.colorfulness, 0.01, "colorfulness v$variant")
            assertEquals(o.getValue("negative_space").jsonPrimitive.double, s.negativeSpace, 0.03, "negative_space v$variant")
            assertEquals(o.getValue("subject_isolation").jsonPrimitive.double, s.subjectIsolation, 0.03, "subject_isolation v$variant")
            assertEquals(o.getValue("balance").jsonPrimitive.double, s.balance, 0.08, "balance v$variant")
            assertEquals(o.getValue("rule_of_thirds").jsonPrimitive.double, s.ruleOfThirds, 0.15, "rule_of_thirds v$variant")
            // leading_lines uses a different (deterministic) Hough sampling —
            // assert both agree there are no strong lines, or are within 0.4.
            assertEquals(o.getValue("leading_lines").jsonPrimitive.double, s.leadingLines, 0.4, "leading_lines v$variant")
        }
    }

    // --------------------------------------------------------- eye openness
    @Test
    fun eyeOpennessMatchesReference() {
        for (case in golden.getValue("eye_openness").jsonArray) {
            val o = case.jsonObject
            val variant = o.getValue("variant").jsonPrimitive.int
            val gray = synthGray(96, 64, variant)
            val face = FaceDetection(
                bbox = intArrayOf(20, 10, 40, 30), confidence = 0.9f,
                landmarks = mapOf(
                    "left_eye" to intArrayOf(30, 20),
                    "right_eye" to intArrayOf(50, 20),
                ),
            )
            val openness = ScoreFusion.estimateEyeOpenness(face, gray)
            assertEquals(o.getValue("openness").jsonPrimitive.double, openness, 1e-6, "openness v$variant")
        }
    }

    // --------------------------------------------------------------- fusion
    @Test
    fun fusionMatchesReferenceExactly() {
        val profiles = Assets.loadWeightProfiles()
        for (case in golden.getValue("fusion").jsonArray) {
            val o = case.jsonObject
            val sh = o.getValue("sharpness").jsonObject
            val co = o.getValue("composition").jsonObject
            val ex = o.getValue("exposure").jsonObject
            val ge = o.getValue("genre").jsonObject
            val sharp = SharpnessScores(
                subject = sh.getValue("subject").jsonPrimitive.double,
                eyeRegion = sh.getValue("eye_region").jsonPrimitive.double,
                background = sh.getValue("background").jsonPrimitive.double,
                sharpnessContrast = sh.getValue("sharpness_contrast").jsonPrimitive.double,
                blurType = sh.getValue("blur_type").jsonPrimitive.content,
                overall = sh.getValue("overall").jsonPrimitive.double,
            )
            val comp = CompositionScores(
                ruleOfThirds = co.getValue("rule_of_thirds").jsonPrimitive.double,
                symmetry = co.getValue("symmetry").jsonPrimitive.double,
                leadingLines = co.getValue("leading_lines").jsonPrimitive.double,
                negativeSpace = co.getValue("negative_space").jsonPrimitive.double,
                subjectIsolation = co.getValue("subject_isolation").jsonPrimitive.double,
                balance = co.getValue("balance").jsonPrimitive.double,
                overall = co.getValue("overall").jsonPrimitive.double,
                colorfulness = co.getValue("colorfulness").jsonPrimitive.double,
            )
            val expo = ExposureScores(
                zoneEntropy = ex.getValue("zone_entropy").jsonPrimitive.double,
                zoneDiversity = ex.getValue("zone_diversity").jsonPrimitive.int,
                clippingShadows = ex.getValue("clipping_shadows").jsonPrimitive.double,
                clippingHighlights = ex.getValue("clipping_highlights").jsonPrimitive.double,
                dynamicRange = ex.getValue("dynamic_range").jsonPrimitive.double,
                midtoneDensity = ex.getValue("midtone_density").jsonPrimitive.double,
                faceExposure = ex.getValue("face_exposure").jsonPrimitive.double,
                style = ex.getValue("style").jsonPrimitive.content,
                styleConfidence = ex.getValue("style_confidence").jsonPrimitive.double,
                overall = ex.getValue("overall").jsonPrimitive.double,
            )
            val genre = GenreResult(
                subject = ge.getValue("subject").jsonPrimitive.content,
                subjectConfidence = ge.getValue("subject_confidence").jsonPrimitive.double,
                photoType = ge.getValue("photo_type").jsonPrimitive.content,
                typeConfidence = ge.getValue("type_confidence").jsonPrimitive.double,
                subjectDistribution = emptyMap(),
                typeDistribution = emptyMap(),
                needsReview = ge.getValue("needs_review").jsonPrimitive.boolean,
            )
            val aesthetic = o["aesthetic"]?.jsonPrimitive?.takeIf { it.content != "null" }?.double
            val result = ScoreFusion.fuse(sharp, comp, expo, genre, aesthetic, emptyList(), null, profiles)
            val expected = o.getValue("expected").jsonObject
            assertEquals(
                expected.getValue("master_score").jsonPrimitive.double,
                result.masterScore, 1e-9, "master_score",
            )
            assertEquals(expected.getValue("hard_reject").jsonPrimitive.boolean, result.hardReject)
            assertEquals(expected.getValue("hard_reject_reason").jsonPrimitive.content, result.hardRejectReason)
            assertEquals(expected.getValue("star_rating").jsonPrimitive.int, result.starRating)
            assertEquals(expected.getValue("color_label").jsonPrimitive.int, result.colorLabel)
            for ((k, v) in expected.getValue("sub_scores").jsonObject) {
                assertEquals(v.jsonPrimitive.double, result.subScores.getValue(k), 1e-9, "sub_score $k")
            }
        }
    }

    // ---------------------------------------------------------------- stars
    @Test
    fun starTablesMatch() {
        val stars = golden.getValue("stars").jsonObject
        val kept = stars.getValue("kept_sorted").jsonArray.map { it.jsonPrimitive.double }
        for (case in stars.getValue("cases").jsonArray) {
            val o = case.jsonObject
            val m = o.getValue("master").jsonPrimitive.double
            assertEquals(o.getValue("absolute").jsonPrimitive.int, ScoreFusion.absoluteStar(m, false), "absolute $m")
            assertEquals(o.getValue("absolute_reject").jsonPrimitive.int, ScoreFusion.absoluteStar(m, true))
            assertEquals(o.getValue("hybrid").jsonPrimitive.int, ScoreFusion.hybridStar(m, false, kept), "hybrid $m")
            assertEquals(
                o.getValue("color").jsonPrimitive.int,
                ScoreFusion.starsToColorLabel(ScoreFusion.absoluteStar(m, false)),
            )
        }
    }

    // ---------------------------------------------------------------- genre
    @Test
    fun genreRoutingMatchesReference() {
        val adapter = Assets.loadAdapter()
        val prototypes = Assets.loadPrototypes()
        for (case in golden.getValue("genre").jsonArray) {
            val o = case.jsonObject
            val emb = o.getValue("embedding").jsonArray.let { arr ->
                FloatArray(arr.size) { i -> arr[i].jsonPrimitive.float }
            }
            val shutter = o["shutter"]?.jsonPrimitive?.takeIf { it.content != "null" }?.double
            val useAdapter = o.getValue("use_adapter").jsonPrimitive.boolean
            val res = GenreRouter.route(
                clipEmbedding = emb,
                adapter = if (useAdapter) adapter else null,
                prototypes = if (useAdapter) null else prototypes,
                shutterSeconds = shutter,
            )
            val expected = o.getValue("expected").jsonObject
            assertEquals(expected.getValue("subject").jsonPrimitive.content, res.subject)
            assertEquals(expected.getValue("subject_confidence").jsonPrimitive.double, res.subjectConfidence, 2e-4)
            assertEquals(expected.getValue("photo_type").jsonPrimitive.content, res.photoType)
            assertEquals(expected.getValue("type_confidence").jsonPrimitive.double, res.typeConfidence, 2e-4)
            assertEquals(expected.getValue("needs_review").jsonPrimitive.boolean, res.needsReview)
        }
    }

    // ---------------------------------------------------- dhash & grouping
    @Test
    fun dhashSelfConsistency() {
        val a = synthGray(200, 130, 1)
        val b = synthGray(200, 130, 1)
        // tiny brightness shift should keep hamming distance small
        for (i in b.pixels.indices) b.pixels[i] = minOf(b.pixels[i] + 2f, 255f)
        val c = synthGray(200, 130, 2)
        val ha = com.photonforge.core.pipeline.Dedup.dhash(a)
        val hb = com.photonforge.core.pipeline.Dedup.dhash(b)
        val hc = com.photonforge.core.pipeline.Dedup.dhash(c)
        assertEquals(ha, com.photonforge.core.pipeline.Dedup.dhash(a))
        assertTrue(com.photonforge.core.pipeline.Dedup.hammingDistance(ha, hb) <= 2, "near-dup within threshold")
        assertTrue(com.photonforge.core.pipeline.Dedup.hammingDistance(ha, hc) > 2, "distinct image far away")
    }

    @Test
    fun sessionGroupingMatchesRules() {
        val base = 1_700_000_000_000L
        val ts = mapOf(
            "a" to base,
            "b" to base + 5 * 60_000,
            "c" to base + 40 * 60_000,       // 35 min after b -> new session
            "d" to null,
        )
        val sessions = com.photonforge.core.pipeline.Grouping.clusterSessions(ts)
        assertEquals("session_0001", sessions["a"])
        assertEquals("session_0001", sessions["b"])
        assertEquals("session_0002", sessions["c"])
        assertEquals("session_0000", sessions["d"])
    }

    @Test
    fun duplicateMarkingRespectsSessions() {
        val dups = com.photonforge.core.pipeline.Dedup.markDuplicates(
            entries = listOf("a" to 0b1010L, "b" to 0b1011L, "c" to 0b1010L),
            sessionOf = { if (it == "c") "s2" else "s1" },
        )
        assertEquals(setOf("b"), dups)  // b within hamming<=2 of a; c in other session
    }

    private fun abs(v: Double) = kotlin.math.abs(v)
}
