package com.photonforge.core.inference

import com.photonforge.core.FaceDetection
import com.photonforge.core.Mask
import com.photonforge.core.ObjectDetection
import com.photonforge.core.RgbImage
import com.photonforge.core.cv.ImageOps
import kotlin.math.max
import kotlin.math.min

/**
 * Tensor building + output decoding for the four scoring models, ported from
 * subject_context.py. All resizes are plain (aspect-ignoring) bilinear — the
 * desktop deliberately does NOT letterbox YOLO/CLIP inputs.
 */
object Preprocess {

    const val CLIP_INPUT_SIZE = 256
    const val RMBG_INPUT_SIZE = 320
    const val YOLO_INPUT_SIZE = 640
    const val YOLO_CONF_THRESHOLD = 0.3f
    const val YOLO_NMS_IOU = 0.45f
    const val YUNET_CONF_THRESHOLD = 0.5f
    const val RMBG_BINARIZE = 0.5f

    val COCO_CLASSES = listOf(
        "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
        "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
        "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
        "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
        "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
        "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
        "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
        "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
        "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
        "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
        "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
        "hair drier", "toothbrush",
    )

    /** RGB HWC uint8 -> CHW float [0,1] at NxN (CLIP/RMBG/YOLO input). */
    fun rgbChwNormalized(img: RgbImage, size: Int): FloatArray {
        val resized = ImageOps.resizeBilinearRgb(img, size, size)
        val out = FloatArray(3 * size * size)
        val plane = size * size
        for (i in 0 until plane) {
            out[i] = (resized.pixels[i * 3].toInt() and 0xFF) / 255f
            out[plane + i] = (resized.pixels[i * 3 + 1].toInt() and 0xFF) / 255f
            out[2 * plane + i] = (resized.pixels[i * 3 + 2].toInt() and 0xFF) / 255f
        }
        return out
    }

    /** BGR CHW float raw 0..255 at (w,h) — YuNet's convention (no /255). */
    fun bgrChwRaw(img: RgbImage, dstW: Int, dstH: Int): FloatArray {
        val resized = ImageOps.resizeBilinearRgb(img, dstW, dstH)
        val out = FloatArray(3 * dstW * dstH)
        val plane = dstW * dstH
        for (i in 0 until plane) {
            out[i] = (resized.pixels[i * 3 + 2].toInt() and 0xFF).toFloat()        // B
            out[plane + i] = (resized.pixels[i * 3 + 1].toInt() and 0xFF).toFloat() // G
            out[2 * plane + i] = (resized.pixels[i * 3].toInt() and 0xFF).toFloat() // R
        }
        return out
    }

    fun l2Normalize(v: FloatArray): FloatArray {
        var s = 0.0
        for (x in v) s += x.toDouble() * x
        val norm = kotlin.math.sqrt(s)
        if (norm == 0.0) return v
        return FloatArray(v.size) { (v[it] / norm).toFloat() }
    }

    /** RMBG mask output (size x size floats) -> full-res binary mask (>0.5). */
    fun rmbgMask(output: FloatArray, size: Int, dstW: Int, dstH: Int): Mask {
        val small = com.photonforge.core.GrayImage(size, size, output.copyOf())
        val full = ImageOps.resizeBilinear(small, dstW, dstH)
        val data = ByteArray(dstW * dstH)
        for (i in data.indices) data[i] = if (full.pixels[i] > RMBG_BINARIZE) 1 else 0
        return Mask(dstW, dstH, data)
    }

    /** YuNet rows [N,15]: x,y,w,h,5x(lx,ly),conf — scaled back to original res. */
    fun yunetFaces(
        rows: Array<FloatArray>,
        modelW: Int,
        modelH: Int,
        origW: Int,
        origH: Int,
    ): List<FaceDetection> {
        val sx = origW.toFloat() / modelW
        val sy = origH.toFloat() / modelH
        val landmarkNames = listOf("right_eye", "left_eye", "nose", "mouth_right", "mouth_left")
        val out = ArrayList<FaceDetection>()
        for (row in rows) {
            if (row.size < 15) continue
            val conf = row[14]
            if (conf < YUNET_CONF_THRESHOLD) continue
            val bbox = intArrayOf(
                (row[0] * sx).toInt(), (row[1] * sy).toInt(),
                (row[2] * sx).toInt(), (row[3] * sy).toInt(),
            )
            val landmarks = HashMap<String, IntArray>()
            for (k in 0 until 5) {
                landmarks[landmarkNames[k]] = intArrayOf(
                    (row[4 + k * 2] * sx).toInt(),
                    (row[5 + k * 2] * sy).toInt(),
                )
            }
            out.add(FaceDetection(bbox, conf, landmarks))
        }
        return out
    }

    /**
     * YOLOv8 output [84, 8400] (already squeezed) -> detections at original res.
     * Matches subject_context: conf 0.3, per-class greedy NMS IoU 0.45,
     * independent x/y scale-back (no letterbox).
     */
    fun yoloDetections(
        output: FloatArray,             // 84 * 8400 row-major [84][8400]
        numCandidates: Int,
        origW: Int,
        origH: Int,
    ): List<ObjectDetection> {
        val sx = origW.toFloat() / YOLO_INPUT_SIZE
        val sy = origH.toFloat() / YOLO_INPUT_SIZE

        class Cand(val box: FloatArray, val score: Float, val classId: Int)
        val cands = ArrayList<Cand>()
        for (i in 0 until numCandidates) {
            var best = 0f
            var bestClass = -1
            for (c in 0 until 80) {
                val s = output[(4 + c) * numCandidates + i]
                if (s > best) { best = s; bestClass = c }
            }
            if (best < YOLO_CONF_THRESHOLD) continue
            val cx = output[i]
            val cy = output[numCandidates + i]
            val w = output[2 * numCandidates + i]
            val h = output[3 * numCandidates + i]
            cands.add(Cand(floatArrayOf(cx - w / 2, cy - h / 2, w, h), best, bestClass))
        }

        // Greedy NMS per class (cv2.dnn.NMSBoxes with class-offset behaviour).
        fun iou(a: FloatArray, b: FloatArray): Float {
            val ax2 = a[0] + a[2]; val ay2 = a[1] + a[3]
            val bx2 = b[0] + b[2]; val by2 = b[1] + b[3]
            val ix = max(0f, min(ax2, bx2) - max(a[0], b[0]))
            val iy = max(0f, min(ay2, by2) - max(a[1], b[1]))
            val inter = ix * iy
            val union = a[2] * a[3] + b[2] * b[3] - inter
            return if (union <= 0f) 0f else inter / union
        }

        val out = ArrayList<ObjectDetection>()
        for (classId in cands.map { it.classId }.distinct()) {
            val classCands = cands.filter { it.classId == classId }.sortedByDescending { it.score }
            val kept = ArrayList<Cand>()
            for (c in classCands) {
                if (kept.none { iou(it.box, c.box) > YOLO_NMS_IOU }) kept.add(c)
            }
            for (c in kept) {
                out.add(
                    ObjectDetection(
                        bbox = intArrayOf(
                            (c.box[0] * sx).toInt(), (c.box[1] * sy).toInt(),
                            (c.box[2] * sx).toInt(), (c.box[3] * sy).toInt(),
                        ),
                        confidence = c.score,
                        classId = c.classId,
                        className = COCO_CLASSES[c.classId],
                    ),
                )
            }
        }
        return out.sortedByDescending { it.confidence }
    }
}
