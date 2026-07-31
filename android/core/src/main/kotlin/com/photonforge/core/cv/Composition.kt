package com.photonforge.core.cv

import com.photonforge.core.CompositionScores
import com.photonforge.core.GrayImage
import com.photonforge.core.Mask
import com.photonforge.core.RgbImage
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** Port of photo_workflow.composition (FR-1.5). */
object Composition {

    // ------------------------------------------------------------------ FFT
    /** In-place radix-2 FFT on interleaved re/im arrays (n power of two). */
    private fun fft(re: DoubleArray, im: DoubleArray, invert: Boolean) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j or bit
            if (i < j) {
                val tr = re[i]; re[i] = re[j]; re[j] = tr
                val ti = im[i]; im[i] = im[j]; im[j] = ti
            }
        }
        var len = 2
        while (len <= n) {
            val ang = 2 * PI / len * (if (invert) 1 else -1)
            val wRe = cos(ang)
            val wIm = sin(ang)
            var i = 0
            while (i < n) {
                var curRe = 1.0
                var curIm = 0.0
                for (k in 0 until len / 2) {
                    val uRe = re[i + k]; val uIm = im[i + k]
                    val vRe = re[i + k + len / 2] * curRe - im[i + k + len / 2] * curIm
                    val vIm = re[i + k + len / 2] * curIm + im[i + k + len / 2] * curRe
                    re[i + k] = uRe + vRe; im[i + k] = uIm + vIm
                    re[i + k + len / 2] = uRe - vRe; im[i + k + len / 2] = uIm - vIm
                    val nRe = curRe * wRe - curIm * wIm
                    curIm = curRe * wIm + curIm * wRe
                    curRe = nRe
                }
                i += len
            }
            len = len shl 1
        }
        if (invert) {
            for (i in 0 until n) { re[i] /= n; im[i] /= n }
        }
    }

    private fun fft2(re: Array<DoubleArray>, im: Array<DoubleArray>, invert: Boolean) {
        val n = re.size
        for (y in 0 until n) fft(re[y], im[y], invert)
        val colRe = DoubleArray(n)
        val colIm = DoubleArray(n)
        for (x in 0 until n) {
            for (y in 0 until n) { colRe[y] = re[y][x]; colIm[y] = im[y][x] }
            fft(colRe, colIm, invert)
            for (y in 0 until n) { re[y][x] = colRe[y]; im[y][x] = colIm[y] }
        }
    }

    /** Spectral residual saliency (Hou & Zhang 2007) at 64x64, upscaled to (w, h). */
    fun saliencyMap(img: RgbImage): GrayImage {
        val gray = img.toGray()
        val small = ImageOps.resizeArea(gray, 64, 64)

        val re = Array(64) { y -> DoubleArray(64) { x -> small.pixels[y * 64 + x].toDouble() } }
        val im = Array(64) { DoubleArray(64) }
        fft2(re, im, invert = false)

        val logAmp = GrayImage(64, 64, FloatArray(64 * 64))
        val phase = Array(64) { DoubleArray(64) }
        for (y in 0 until 64) {
            for (x in 0 until 64) {
                val amp = sqrt(re[y][x] * re[y][x] + im[y][x] * im[y][x])
                logAmp[y, x] = ln(amp + 1e-8).toFloat()
                phase[y][x] = kotlin.math.atan2(im[y][x], re[y][x])
            }
        }
        val avgLogAmp = ImageOps.boxFilter3(logAmp)

        val srRe = Array(64) { DoubleArray(64) }
        val srIm = Array(64) { DoubleArray(64) }
        for (y in 0 until 64) {
            for (x in 0 until 64) {
                val mag = exp((logAmp[y, x] - avgLogAmp[y, x]).toDouble())
                srRe[y][x] = mag * cos(phase[y][x])
                srIm[y][x] = mag * sin(phase[y][x])
            }
        }
        fft2(srRe, srIm, invert = true)

        var sal = GrayImage(64, 64, FloatArray(64 * 64) { i ->
            val y = i / 64; val x = i % 64
            val m2 = srRe[y][x] * srRe[y][x] + srIm[y][x] * srIm[y][x]
            m2.toFloat()
        })
        sal = ImageOps.gaussianBlur(sal, 5, 2.5)

        var mn = Float.MAX_VALUE
        var mx = -Float.MAX_VALUE
        for (v in sal.pixels) { mn = min(mn, v); mx = max(mx, v) }
        if (mx > mn) {
            for (i in sal.pixels.indices) sal.pixels[i] = (sal.pixels[i] - mn) / (mx - mn)
        } else {
            for (i in sal.pixels.indices) sal.pixels[i] = 0f
        }
        return ImageOps.resizeBilinear(sal, img.width, img.height)
    }

    fun ruleOfThirds(saliency: GrayImage): Double {
        val h = saliency.height
        val w = saliency.width
        val diagonal = sqrt((h.toDouble() * h) + (w.toDouble() * w))
        val sigma = 0.1
        val powerPoints = listOf(
            h / 3.0 to w / 3.0, h / 3.0 to 2 * w / 3.0,
            2 * h / 3.0 to w / 3.0, 2 * h / 3.0 to 2 * w / 3.0,
        )
        val meanV = ImageOps.mean(saliency.pixels)
        val stdV = ImageOps.std(saliency.pixels)
        val threshold = meanV + stdV

        var wSum = 0.0
        var cy = 0.0
        var cx = 0.0
        for (y in 0 until h) {
            for (x in 0 until w) {
                val v = saliency[y, x]
                if (v > threshold) {
                    wSum += v
                    cy += y * v
                    cx += x * v
                }
            }
        }
        if (wSum == 0.0) return 0.0
        cy /= wSum
        cx /= wSum

        var best = 0.0
        for ((py, px) in powerPoints) {
            val d = sqrt((cy - py) * (cy - py) + (cx - px) * (cx - px)) / diagonal
            best = max(best, exp(-d * d / (2 * sigma * sigma)))
        }
        return min(best, 1.0)
    }

    fun symmetry(img: RgbImage): Double {
        var gray = img.toGray()
        val scale = min(1.0, 256.0 / max(gray.width, gray.height))
        if (scale < 1.0) {
            gray = ImageOps.resizeBilinear(
                gray,
                max((gray.width * scale).toInt(), 1),
                max((gray.height * scale).toInt(), 1),
            )
        }
        gray = ImageOps.gaussianBlur(gray, 5, 0.0)

        val w = gray.width
        val h = gray.height
        val meanA = ImageOps.mean(gray.pixels)
        var num = 0.0
        var denA = 0.0
        var denB = 0.0
        // flipped image has the same mean
        for (y in 0 until h) {
            for (x in 0 until w) {
                val a = gray[y, x] - meanA
                val b = gray[y, w - 1 - x] - meanA
                num += a * b
                denA += a * a
                denB += b * b
            }
        }
        val denom = sqrt(denA * denB)
        if (denom < 1e-6) return 0.0
        return max(0.0, num / denom)
    }

    fun colorfulness(img: RgbImage): Double {
        val n = img.width * img.height
        val rg = FloatArray(n)
        val yb = FloatArray(n)
        for (i in 0 until n) {
            val r = (img.pixels[i * 3].toInt() and 0xFF).toFloat()
            val g = (img.pixels[i * 3 + 1].toInt() and 0xFF).toFloat()
            val b = (img.pixels[i * 3 + 2].toInt() and 0xFF).toFloat()
            rg[i] = r - g
            yb[i] = 0.5f * (r + g) - b
        }
        val stdRoot = sqrt(ImageOps.std(rg) * ImageOps.std(rg) + ImageOps.std(yb) * ImageOps.std(yb))
        val meanRoot = sqrt(ImageOps.mean(rg) * ImageOps.mean(rg) + ImageOps.mean(yb) * ImageOps.mean(yb))
        return min((stdRoot + 0.3 * meanRoot) / 100.0, 1.0)
    }

    // -------------------------------------------------------------- Canny
    /** cv2.Canny(50, 150) with L1 gradient, 4-direction NMS + hysteresis. */
    fun canny(gray: GrayImage, lowThresh: Double = 50.0, highThresh: Double = 150.0): Mask {
        val w = gray.width
        val h = gray.height
        val gx = ImageOps.sobelX(gray)
        val gy = ImageOps.sobelY(gray)
        val mag = FloatArray(w * h)
        for (i in mag.indices) mag[i] = abs(gx[i]) + abs(gy[i])   // L1, cv2 default

        val strong = ByteArray(w * h)
        val weak = ByteArray(w * h)
        for (y in 1 until h - 1) {
            for (x in 1 until w - 1) {
                val i = y * w + x
                val m = mag[i]
                if (m < lowThresh) continue
                val dx = gx[i]
                val dy = gy[i]
                val adx = abs(dx)
                val ady = abs(dy)
                // Direction quantization (OpenCV uses tan22.5 boundaries)
                val tan225 = 0.4142135f
                val tan675 = 2.4142135f
                val ratio = if (adx > 1e-9f) ady / adx else Float.MAX_VALUE
                val (n1, n2) = when {
                    ratio < tan225 -> i - 1 to i + 1                              // horizontal gradient
                    ratio > tan675 -> i - w to i + w                              // vertical
                    dx * dy > 0 -> (i - w - 1) to (i + w + 1)                     // 45 diag
                    else -> (i - w + 1) to (i + w - 1)                            // 135 diag
                }
                if (m >= mag[n1] && m > mag[n2]) {
                    if (m >= highThresh) strong[i] = 1 else weak[i] = 1
                }
            }
        }
        // Hysteresis: BFS from strong pixels through weak ones.
        val out = ByteArray(w * h)
        val stack = ArrayDeque<Int>()
        for (i in strong.indices) if (strong[i].toInt() == 1) { out[i] = 1; stack.addLast(i) }
        while (stack.isNotEmpty()) {
            val i = stack.removeLast()
            val y = i / w
            val x = i % w
            for (dy in -1..1) {
                for (dx in -1..1) {
                    val yy = y + dy
                    val xx = x + dx
                    if (yy in 0 until h && xx in 0 until w) {
                        val j = yy * w + xx
                        if (out[j].toInt() == 0 && weak[j].toInt() == 1) {
                            out[j] = 1
                            stack.addLast(j)
                        }
                    }
                }
            }
        }
        return Mask(w, h, out)
    }

    data class Line(val x1: Int, val y1: Int, val x2: Int, val y2: Int)

    /**
     * Progressive probabilistic Hough transform (HoughLinesP semantics:
     * rho=1, theta=pi/180, threshold=50, maxLineGap=10). Deterministic
     * (seeded shuffle) rather than cv2's RNG — line sets differ slightly
     * from OpenCV but the convergence statistic downstream is stable.
     */
    fun houghLinesP(
        edges: Mask,
        threshold: Int = 50,
        minLineLength: Int,
        maxLineGap: Int = 10,
    ): List<Line> {
        val w = edges.width
        val h = edges.height
        val numAngle = 180
        val numRho = (2 * (w + h) + 1)
        val rhoOffset = w + h
        val accum = IntArray(numAngle * numRho)
        val cosT = DoubleArray(numAngle) { cos(it * PI / 180.0) }
        val sinT = DoubleArray(numAngle) { sin(it * PI / 180.0) }

        val points = ArrayList<Int>()
        for (i in edges.data.indices) if (edges.data[i].toInt() == 1) points.add(i)
        // Deterministic shuffle (LCG) so results are reproducible.
        var seed = 0x12345678L
        for (i in points.indices.reversed()) {
            seed = (seed * 6364136223846793005L + 1442695040888963407L)
            val j = ((seed ushr 33) % (i + 1)).toInt()
            val t = points[i]; points[i] = points[j]; points[j] = t
        }
        val alive = ByteArray(w * h)
        for (i in edges.data.indices) alive[i] = edges.data[i]

        val lines = ArrayList<Line>()
        for (p in points) {
            if (alive[p].toInt() == 0) continue
            val py = p / w
            val px = p % w
            // Vote
            var bestN = 0
            var bestAngle = -1
            for (a in 0 until numAngle) {
                val rho = (px * cosT[a] + py * sinT[a]).toInt() + rhoOffset
                val idx = a * numRho + rho
                accum[idx]++
                if (accum[idx] > bestN) { bestN = accum[idx]; bestAngle = a }
            }
            if (bestN < threshold) continue

            // Walk the line direction from this point both ways.
            val dirX = -sinT[bestAngle]
            val dirY = cosT[bestAngle]
            val ends = Array(2) { intArrayOf(px, py) }
            for (dir in 0..1) {
                val sign = if (dir == 0) 1.0 else -1.0
                var cx = px.toDouble()
                var cy = py.toDouble()
                var gap = 0
                while (true) {
                    cx += dirX * sign
                    cy += dirY * sign
                    val ix = Math.round(cx).toInt()
                    val iy = Math.round(cy).toInt()
                    if (ix < 0 || ix >= w || iy < 0 || iy >= h) break
                    if (alive[iy * w + ix].toInt() == 1) {
                        gap = 0
                        ends[dir][0] = ix
                        ends[dir][1] = iy
                    } else {
                        gap++
                        if (gap > maxLineGap) break
                    }
                }
            }
            val dx = ends[0][0] - ends[1][0]
            val dy = ends[0][1] - ends[1][1]
            val length = sqrt((dx * dx + dy * dy).toDouble())
            // Un-vote pixels on the segment & mark consumed.
            for (dir in 0..1) {
                val sign = if (dir == 0) 1.0 else -1.0
                var cx = px.toDouble()
                var cy = py.toDouble()
                while (true) {
                    val ix = Math.round(cx).toInt()
                    val iy = Math.round(cy).toInt()
                    if (ix < 0 || ix >= w || iy < 0 || iy >= h) break
                    if (alive[iy * w + ix].toInt() == 1) {
                        alive[iy * w + ix] = 0
                        for (a in 0 until numAngle) {
                            val rho = (ix * cosT[a] + iy * sinT[a]).toInt() + rhoOffset
                            accum[a * numRho + rho]--
                        }
                    }
                    if (ix == ends[dir][0] && iy == ends[dir][1]) break
                    cx += dirX * sign
                    cy += dirY * sign
                }
            }
            if (length >= minLineLength) {
                lines.add(Line(ends[1][0], ends[1][1], ends[0][0], ends[0][1]))
            }
        }
        return lines
    }

    fun leadingLines(img: RgbImage, subjectCentroid: Pair<Double, Double>): Double {
        var gray = img.toGray()
        val h0 = gray.height
        val w0 = gray.width
        val scale = min(1.0, 1024.0 / max(h0, w0))
        var cx = subjectCentroid.first
        var cy = subjectCentroid.second
        if (scale < 1.0) {
            gray = ImageOps.resizeBilinear(gray, (w0 * scale).toInt(), (h0 * scale).toInt())
            cx *= scale
            cy *= scale
        }
        val diagS = sqrt(gray.height.toDouble() * gray.height + gray.width.toDouble() * gray.width)
        val edges = canny(gray)
        val minLength = (0.15 * diagS).toInt()
        val lines = houghLinesP(edges, threshold = 50, minLineLength = minLength, maxLineGap = 10)
        if (lines.isEmpty()) return 0.0

        var convergence = 0.0
        var totalWeight = 0.0
        for (l in lines) {
            val dx = (l.x2 - l.x1).toDouble()
            val dy = (l.y2 - l.y1).toDouble()
            val norm = sqrt(dx * dx + dy * dy)
            if (norm == 0.0) continue
            val length = norm
            val dist = abs(dy * cx - dx * cy + l.x2.toDouble() * l.y1 - l.y2.toDouble() * l.x1) / norm
            if (dist < 0.15 * diagS) convergence += length
            totalWeight += length
        }
        if (totalWeight == 0.0) return 0.0
        return min(convergence / totalWeight, 1.0)
    }

    fun negativeSpace(mask: Mask, gray: GrayImage): Double {
        val total = mask.width * mask.height
        val subjectPixels = mask.sum()
        val negativeRatio = 1.0 - subjectPixels.toDouble() / max(total, 1)
        val ratioScore = exp(-(negativeRatio - 0.7) * (negativeRatio - 0.7) / (2 * 0.15 * 0.15))

        var smoothness = 0.0
        val bgCount = total - subjectPixels
        if (bgCount > 0) {
            // Match Python: zero the subject region first, THEN Sobel the whole
            // frame (transition edges bleed into the background ring).
            val zeroed = GrayImage(gray.width, gray.height, FloatArray(total) { i ->
                if (mask.data[i].toInt() == 0) gray.pixels[i] else 0f
            })
            val gx = ImageOps.sobelX(zeroed)
            val gy = ImageOps.sobelY(zeroed)
            var s = 0.0
            for (i in 0 until total) {
                if (mask.data[i].toInt() == 0) {
                    s += sqrt(gx[i].toDouble() * gx[i] + gy[i].toDouble() * gy[i])
                }
            }
            val meanGrad = s / bgCount
            smoothness = max(0.0, 1.0 - meanGrad / 100.0)
        }
        return ratioScore * 0.6 + smoothness * 0.4
    }

    fun subjectIsolation(img: RgbImage, mask: Mask, sharpnessContrast: Double): Double {
        var subjL = 0.0; var subjA = 0.0; var subjB = 0.0; var nSubj = 0L
        var bgL = 0.0; var bgA = 0.0; var bgB = 0.0; var nBg = 0L
        val n = img.width * img.height
        for (i in 0 until n) {
            val lab = ImageOps.rgbToLab(
                img.pixels[i * 3].toInt() and 0xFF,
                img.pixels[i * 3 + 1].toInt() and 0xFF,
                img.pixels[i * 3 + 2].toInt() and 0xFF,
            )
            if (mask.data[i].toInt() != 0) {
                subjL += lab[0]; subjA += lab[1]; subjB += lab[2]; nSubj++
            } else {
                bgL += lab[0]; bgA += lab[1]; bgB += lab[2]; nBg++
            }
        }
        if (nSubj == 0L || nBg == 0L) return 0.0
        subjL /= nSubj; subjA /= nSubj; subjB /= nSubj
        bgL /= nBg; bgA /= nBg; bgB /= nBg

        val deltaE = sqrt((subjL - bgL) * (subjL - bgL) + (subjA - bgA) * (subjA - bgA) + (subjB - bgB) * (subjB - bgB))
        val colorContrast = min(deltaE / 50.0, 1.0)
        val lumaContrast = min(abs(subjL - bgL) / 100.0, 1.0)
        val sharpNorm = min(sharpnessContrast / 5.0, 1.0)
        return min(0.4 * sharpNorm + 0.35 * colorContrast + 0.25 * lumaContrast, 1.0)
    }

    fun balance(saliency: GrayImage): Double {
        val h = saliency.height
        val w = saliency.width
        var total = 0.0
        var cy = 0.0
        var cx = 0.0
        for (y in 0 until h) {
            for (x in 0 until w) {
                val v = saliency[y, x]
                total += v
                cy += y * v
                cx += x * v
            }
        }
        if (total == 0.0) return 0.5
        cy /= total
        cx /= total
        val dist = sqrt((cy - h / 2.0) * (cy - h / 2.0) + (cx - w / 2.0) * (cx - w / 2.0))
        val halfDiag = sqrt(h.toDouble() * h + w.toDouble() * w) / 2
        return max(0.0, min(1.0 - dist / halfDiag, 1.0))
    }

    fun score(img: RgbImage, gray: GrayImage, mask: Mask): CompositionScores {
        val saliency = try {
            saliencyMap(img)
        } catch (e: Exception) {
            GrayImage(img.width, img.height, FloatArray(img.width * img.height))
        }

        var cxSum = 0.0
        var cySum = 0.0
        var nMask = 0L
        for (y in 0 until mask.height) {
            for (x in 0 until mask.width) {
                if (mask[y, x] != 0) { cxSum += x; cySum += y; nMask++ }
            }
        }
        val centroid = if (nMask > 0) (cxSum / nMask) to (cySum / nMask)
        else (gray.width / 2.0) to (gray.height / 2.0)

        val rot = ruleOfThirds(saliency)
        val sym = symmetry(img)
        val lines = leadingLines(img, centroid)
        val negSpace = negativeSpace(mask, gray)

        val maps = Sharpness.focusMaps(gray)
        val subjSharp = Sharpness.regionScoreFromMaps(maps, gray, mask)
        val bgSharp = Sharpness.regionScoreFromMaps(maps, gray, mask.inverted())
        val sharpContrast = subjSharp / max(bgSharp, 0.01)

        val isolation = subjectIsolation(img, mask, sharpContrast)
        val bal = balance(saliency)
        val colorful = colorfulness(img)

        val overall = (rot + sym + lines + negSpace + isolation + bal) / 6.0

        return CompositionScores(
            ruleOfThirds = round4(rot),
            symmetry = round4(sym),
            leadingLines = round4(lines),
            negativeSpace = round4(negSpace),
            subjectIsolation = round4(isolation),
            balance = round4(bal),
            overall = round4(overall),
            colorfulness = round4(colorful),
        )
    }
}
