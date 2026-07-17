package com.photonforge.app.pipeline

import android.content.Context
import android.graphics.BitmapFactory
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import androidx.documentfile.provider.DocumentFile
import com.photonforge.app.inference.EngineRegistry
import com.photonforge.app.inference.InferenceEngine
import com.photonforge.core.Assets
import com.photonforge.core.FaceDetection
import com.photonforge.core.GrayImage
import com.photonforge.core.Mask
import com.photonforge.core.ObjectDetection
import com.photonforge.core.RgbImage
import com.photonforge.core.arw.ArwPreview
import com.photonforge.core.cv.Composition
import com.photonforge.core.cv.Exposure
import com.photonforge.core.cv.Sharpness
import com.photonforge.core.fusion.ScoreFusion
import com.photonforge.core.genre.GenreRouter
import com.photonforge.core.inference.Preprocess
import com.photonforge.core.pipeline.Dedup
import com.photonforge.core.pipeline.Grouping
import com.photonforge.core.xmp.XmpSidecar
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private const val TAG = "PhotonForge"

/**
 * Phase 2 headless core: enumerate ARW files in a tree URI, extract embedded
 * previews, run the four scoring models + classical CV + fusion, write XMP
 * sidecars, and log per-frame stage timings + thermal headroom to a CSV.
 * This IS the benchmark harness — the CSV is the deliverable.
 */
class PipelineRunner(
    private val context: Context,
    private val log: (String) -> Unit,
) {
    /** Bytes of file head read for IFD + preview (Sony previews live up front). */
    private val headBytes = 2 * 1024 * 1024

    class Models(
        val clip: InferenceEngine.Session,
        val rmbg: InferenceEngine.Session?,
        val yunet: InferenceEngine.Session?,
        val yolo: InferenceEngine.Session?,
        val aesthetic: InferenceEngine.Session?,
    )

    private val registry = EngineRegistry().apply {
        onFallback = { model, engine, e ->
            log("engine $engine failed for $model -> cpu: ${e.message}")
        }
    }

    fun loadModels(modelsTree: DocumentFile): Models {
        fun bytes(vararg path: String): ByteArray? {
            var dir: DocumentFile = modelsTree
            for (p in path.dropLast(1)) dir = dir.findFile(p) ?: return null
            val f = dir.findFile(path.last()) ?: return null
            return context.contentResolver.openInputStream(f.uri)?.use { it.readBytes() }
        }
        fun load(name: String, vararg path: String): InferenceEngine.Session? {
            val b = bytes(*path) ?: run { log("model $name missing (${path.joinToString("/")})"); return null }
            val t0 = SystemClock.elapsedRealtime()
            val s = registry.load(name, b)
            log("loaded $name (${b.size / 1024 / 1024} MB) in ${SystemClock.elapsedRealtime() - t0} ms")
            return s
        }
        val clip = load("clip", "mobileclip_s2_int8", "vision_encoder.onnx")
            ?: error("MobileCLIP model is required (mobileclip_s2_int8/vision_encoder.onnx)")
        return Models(
            clip = clip,
            rmbg = load("rmbg", "rmbg14_int8", "model.onnx"),
            yunet = load("yunet", "yunet", "face_detection_yunet.onnx"),
            yolo = load("yolo", "yolov8n_int8", "model.onnx"),
            aesthetic = load("aesthetic", "clip_aesthetic_head", "aesthetic_mlp.onnx"),
        )
    }

    data class FrameResult(
        val name: String,
        val master: Double,
        val stars: Int,
        val reject: Boolean,
        val subject: String,
        val photoType: String,
        val timings: Map<String, Long>,
    )

    fun run(photosTree: DocumentFile, modelsTree: DocumentFile, writeXmp: Boolean = true) {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        val runStamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        val csv = File(context.getExternalFilesDir("benchmarks"), "run-$runStamp.csv")
        csv.parentFile?.mkdirs()
        csv.appendText(
            "name,previewLocateMs,previewDecodeMs,clipMs,rmbgMs,yunetMs,yoloMs,aestheticMs," +
                "classicalMs,fusionMs,xmpMs,totalMs,previewW,previewH,thermalHeadroom,thermalStatus," +
                "master,stars,reject,subject,photoType\n"
        )
        log("csv -> ${csv.absolutePath}")

        val models = loadModels(modelsTree)
        val profiles = Assets.loadWeightProfiles()
        val adapter = Assets.loadAdapter()
        val prototypes = Assets.loadPrototypes()

        val arwFiles = photosTree.listFiles()
            .filter { it.isFile && (it.name ?: "").lowercase().endsWith(".arw") }
            .sortedBy { it.name }
        log("found ${arwFiles.size} ARW files")

        // Pass 1: EXIF timestamps for session grouping (header reads only).
        val heads = HashMap<String, ByteArray>()
        val timestamps = HashMap<String, Long?>()
        val exposures = HashMap<String, Double?>()
        val fmt = SimpleDateFormat("yyyy:MM:dd HH:mm:ss", Locale.US)
        for (f in arwFiles) {
            val name = f.name ?: continue
            try {
                val head = context.contentResolver.openInputStream(f.uri)?.use {
                    it.readNBytes(headBytes)
                } ?: continue
                heads[name] = head
                val parsed = ArwPreview.parse(head)
                timestamps[name] = parsed.dateTimeOriginal?.let {
                    try { fmt.parse(it)?.time } catch (e: Exception) { null }
                }
                exposures[name] = parsed.exposureSeconds
            } catch (e: Exception) {
                log("header parse failed for $name: ${e.message}")
                timestamps[name] = null
            }
        }
        val sessions = Grouping.clusterSessions(timestamps)

        // Pass 2: score every frame, streaming; collect masters for hybrid pass.
        val hashesSeen = HashMap<String, MutableList<Long>>()
        val results = ArrayList<FrameResult>()
        val masters = ArrayList<Double>()

        for ((index, f) in arwFiles.withIndex()) {
            val name = f.name ?: continue
            val head = heads[name] ?: continue
            val tTotal0 = SystemClock.elapsedRealtimeNanos()
            val timings = LinkedHashMap<String, Long>()
            fun <T> timed(key: String, block: () -> T): T {
                val t0 = SystemClock.elapsedRealtimeNanos()
                val r = block()
                timings[key] = (SystemClock.elapsedRealtimeNanos() - t0) / 1_000_000
                return r
            }
            try {
                val preview = timed("previewLocate") { ArwPreview.parse(head) }
                val rgb = timed("previewDecode") { decodePreview(f, head, preview) }
                val gray = rgb.toGray()
                // round to uint8 to match the calibrated thresholds
                for (i in gray.pixels.indices) gray.pixels[i] = Math.round(gray.pixels[i]).toFloat()

                // dedup within session
                val hash = Dedup.dhash(gray)
                val session = sessions[name] ?: "session_0000"
                val bucket = hashesSeen.getOrPut(session) { mutableListOf() }
                val isDup = bucket.any { Dedup.hammingDistance(it, hash) <= Dedup.DHASH_THRESHOLD }
                if (!isDup) bucket.add(hash)

                // models
                val clipEmb = timed("clip") {
                    val (_, out) = models.clip.run(
                        Preprocess.rgbChwNormalized(rgb, Preprocess.CLIP_INPUT_SIZE),
                        longArrayOf(1, 3, 256, 256),
                    )
                    Preprocess.l2Normalize(out)
                }
                val mask = timed("rmbg") {
                    models.rmbg?.let {
                        val (shape, out) = it.run(
                            Preprocess.rgbChwNormalized(rgb, Preprocess.RMBG_INPUT_SIZE),
                            longArrayOf(1, 3, 320, 320),
                        )
                        val side = shape.last().toInt()
                        Preprocess.rmbgMask(out, side, rgb.width, rgb.height)
                    } ?: Mask.full(rgb.width, rgb.height)
                }
                val faces = timed("yunet") {
                    models.yunet?.let { detectFaces(it, rgb) } ?: emptyList()
                }
                val detections = timed("yolo") {
                    models.yolo?.let {
                        val (shape, out) = it.run(
                            Preprocess.rgbChwNormalized(rgb, Preprocess.YOLO_INPUT_SIZE),
                            longArrayOf(1, 3, 640, 640),
                        )
                        Preprocess.yoloDetections(out, shape.last().toInt(), rgb.width, rgb.height)
                    } ?: emptyList<ObjectDetection>()
                }
                val aesthetic = timed("aesthetic") {
                    models.aesthetic?.let {
                        val (_, out) = it.run(clipEmb, longArrayOf(1, 512))
                        out.firstOrNull()?.toDouble()?.coerceIn(0.0, 1.0)
                    }
                }

                // classical CV + routing + fusion
                val (sharpness, composition, exposure) = timed("classical") {
                    Triple(
                        Sharpness.score(gray, mask, faces, detections),
                        Composition.score(rgb, gray, mask),
                        Exposure.score(rgb, faces),
                    )
                }
                val fusion = timed("fusion") {
                    val genre = GenreRouter.route(clipEmb, adapter, prototypes, exposures[name])
                    ScoreFusion.fuse(sharpness, composition, exposure, genre, aesthetic, faces, gray, profiles)
                }

                val stars = ScoreFusion.absoluteStar(fusion.masterScore, fusion.hardReject)
                if (writeXmp) {
                    timed("xmp") {
                        writeSidecar(
                            photosTree, name,
                            XmpSidecar.SidecarData(
                                fusion = fusion,
                                originalFilename = name,
                                sessionId = session,
                                isDuplicate = isDup,
                                rating = if (fusion.hardReject) -1 else stars,
                                sharpnessOverall = sharpness.overall,
                                compositionOverall = composition.overall,
                                exposureOverall = exposure.overall,
                                blurType = sharpness.blurType,
                                exposureStyle = exposure.style,
                            ),
                        )
                    }
                } else timings["xmp"] = 0

                val totalMs = (SystemClock.elapsedRealtimeNanos() - tTotal0) / 1_000_000
                val headroom = try { pm.getThermalHeadroom(0) } catch (e: Exception) { Float.NaN }
                val status = pm.currentThermalStatus
                if (!fusion.hardReject && fusion.masterScore >= ScoreFusion.RATING_ABS_FLOOR) {
                    masters.add(fusion.masterScore)
                }
                results.add(FrameResult(name, fusion.masterScore, stars, fusion.hardReject,
                    fusion.subject, fusion.photoType, timings))

                csv.appendText(
                    "$name,${timings["previewLocate"]},${timings["previewDecode"]},${timings["clip"]}," +
                        "${timings["rmbg"]},${timings["yunet"]},${timings["yolo"]},${timings["aesthetic"]}," +
                        "${timings["classical"]},${timings["fusion"]},${timings["xmp"]},$totalMs," +
                        "${rgb.width},${rgb.height},$headroom,$status," +
                        "${fusion.masterScore},$stars,${fusion.hardReject},${fusion.subject},${fusion.photoType}\n"
                )
                log(
                    "[${index + 1}/${arwFiles.size}] $name ${totalMs}ms " +
                        "(decode ${timings["previewDecode"]} clip ${timings["clip"]} " +
                        "cv ${timings["classical"]}) master=${fusion.masterScore} " +
                        "${stars}★ ${fusion.subject}/${fusion.photoType}" +
                        (if (isDup) " DUP" else "") + (if (fusion.hardReject) " REJECT" else "")
                )
            } catch (e: Exception) {
                Log.e(TAG, "frame failed: $name", e)
                log("[${index + 1}/${arwFiles.size}] $name FAILED: ${e.message}")
            }
        }

        // Final relative re-rating (hybrid_star): report only, XMP keeps rating.
        masters.sort()
        var changed = 0
        for (r in results) {
            if (!r.reject) {
                val hybrid = ScoreFusion.hybridStar(r.master, false, masters)
                if (hybrid != r.stars) changed++
            }
        }
        log("done: ${results.size} frames; hybrid re-rating would change $changed stars")
        log("benchmark CSV: ${csv.absolutePath}")
    }

    private fun decodePreview(f: DocumentFile, head: ByteArray, p: ArwPreview.Result): RgbImage {
        val bytes: ByteArray = if (p.previewOffset + p.previewLength <= head.size) {
            head.copyOfRange(p.previewOffset.toInt(), (p.previewOffset + p.previewLength).toInt())
        } else {
            context.contentResolver.openInputStream(f.uri)?.use { s ->
                s.skip(p.previewOffset)
                s.readNBytes(p.previewLength.toInt())
            } ?: error("cannot re-open ${f.name}")
        }
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: error("preview JPEG decode failed")
        val px = IntArray(bmp.width * bmp.height)
        bmp.getPixels(px, 0, bmp.width, 0, 0, bmp.width, bmp.height)
        val out = ByteArray(px.size * 3)
        for (i in px.indices) {
            out[i * 3] = ((px[i] shr 16) and 0xFF).toByte()
            out[i * 3 + 1] = ((px[i] shr 8) and 0xFF).toByte()
            out[i * 3 + 2] = (px[i] and 0xFF).toByte()
        }
        val img = RgbImage(bmp.width, bmp.height, out)
        bmp.recycle()
        return img
    }

    private fun detectFaces(session: InferenceEngine.Session, rgb: RgbImage): List<FaceDetection> {
        val shape = session.inputShape
        var h = shape?.getOrNull(2)?.toInt() ?: 320
        var w = shape?.getOrNull(3)?.toInt() ?: 320
        if (h <= 0) h = 320
        if (w <= 0) w = 320
        val (outShape, out) = session.run(
            Preprocess.bgrChwRaw(rgb, w, h),
            longArrayOf(1, 3, h.toLong(), w.toLong()),
        )
        val cols = outShape.last().toInt()
        if (cols < 15) return emptyList()
        val rows = out.size / cols
        val rowArr = Array(rows) { r -> FloatArray(cols) { c -> out[r * cols + c] } }
        return Preprocess.yunetFaces(rowArr, w, h, rgb.width, rgb.height)
    }

    private fun writeSidecar(tree: DocumentFile, photoName: String, data: XmpSidecar.SidecarData) {
        val sidecarName = XmpSidecar.sidecarName(photoName)
        val existing = tree.findFile(sidecarName)
        val existingBytes = existing?.let {
            context.contentResolver.openInputStream(it.uri)?.use { s -> s.readBytes() }
        }
        val rendered = XmpSidecar.render(existingBytes, data)

        // temp + swap so a crash never leaves a truncated sidecar
        val tmpName = "$sidecarName.tmp"
        tree.findFile(tmpName)?.delete()
        val tmp = tree.createFile("application/rdf+xml", tmpName)
            ?: error("cannot create $tmpName")
        context.contentResolver.openOutputStream(tmp.uri, "wt")?.use {
            it.write(rendered.toByteArray())
        } ?: error("cannot write $tmpName")
        existing?.delete()
        if (!tmp.renameTo(sidecarName)) {
            // Some providers append extensions on createFile; fall back to direct write.
            val direct = tree.createFile("application/rdf+xml", sidecarName)
            direct?.let { d ->
                context.contentResolver.openOutputStream(d.uri, "wt")?.use {
                    it.write(rendered.toByteArray())
                }
            }
            tmp.delete()
        }
    }
}
