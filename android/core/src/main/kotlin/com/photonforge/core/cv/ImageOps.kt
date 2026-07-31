package com.photonforge.core.cv

import com.photonforge.core.GrayImage
import com.photonforge.core.Mask
import com.photonforge.core.RgbImage
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Pixel math ported from the OpenCV calls in the Python reference. Border
 * handling matches cv2's default BORDER_REFLECT_101 (edge pixel not repeated:
 * index -1 -> 1, index n -> n-2).
 */
object ImageOps {

    fun reflect101(i: Int, n: Int): Int {
        if (n == 1) return 0
        var v = i
        while (v < 0 || v >= n) {
            v = if (v < 0) -v else 2 * (n - 1) - v
        }
        return v
    }

    /** Separable 3-tap convolution (kx horizontal, ky vertical), reflect-101 borders. */
    fun convolveSeparable3(src: GrayImage, kx: FloatArray, ky: FloatArray): FloatArray {
        val w = src.width
        val h = src.height
        val tmp = FloatArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                var s = 0f
                for (k in -1..1) {
                    s += kx[k + 1] * src.pixels[y * w + reflect101(x + k, w)]
                }
                tmp[y * w + x] = s
            }
        }
        val out = FloatArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                var s = 0f
                for (k in -1..1) {
                    s += ky[k + 1] * tmp[reflect101(y + k, h) * w + x]
                }
                out[y * w + x] = s
            }
        }
        return out
    }

    /** cv2.Sobel(dx=1, dy=0, ksize=3): kx=[-1,0,1], ky=[1,2,1]. */
    fun sobelX(src: GrayImage): FloatArray =
        convolveSeparable3(src, floatArrayOf(-1f, 0f, 1f), floatArrayOf(1f, 2f, 1f))

    /** cv2.Sobel(dx=0, dy=1, ksize=3). */
    fun sobelY(src: GrayImage): FloatArray =
        convolveSeparable3(src, floatArrayOf(1f, 2f, 1f), floatArrayOf(-1f, 0f, 1f))

    /** cv2.Sobel(dx=2, dy=0, ksize=3): kx=[1,-2,1], ky=[1,2,1]. */
    fun sobelXX(src: GrayImage): FloatArray =
        convolveSeparable3(src, floatArrayOf(1f, -2f, 1f), floatArrayOf(1f, 2f, 1f))

    /** cv2.Sobel(dx=0, dy=2, ksize=3). */
    fun sobelYY(src: GrayImage): FloatArray =
        convolveSeparable3(src, floatArrayOf(1f, 2f, 1f), floatArrayOf(1f, -2f, 1f))

    /** cv2.Laplacian(ksize=1): kernel [[0,1,0],[1,-4,1],[0,1,0]], reflect-101. */
    fun laplacian(src: GrayImage): FloatArray {
        val w = src.width
        val h = src.height
        val out = FloatArray(w * h)
        for (y in 0 until h) {
            val yUp = reflect101(y - 1, h)
            val yDn = reflect101(y + 1, h)
            for (x in 0 until w) {
                val xL = reflect101(x - 1, w)
                val xR = reflect101(x + 1, w)
                out[y * w + x] = src.pixels[yUp * w + x] + src.pixels[yDn * w + x] +
                    src.pixels[y * w + xL] + src.pixels[y * w + xR] -
                    4f * src.pixels[y * w + x]
            }
        }
        return out
    }

    /** 3x3 binary erosion (cv2.erode with ones((3,3)), border replicating outside as 0-safe). */
    fun erode3(mask: Mask): Mask {
        val w = mask.width
        val h = mask.height
        val out = ByteArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                var keep = true
                loop@ for (dy in -1..1) {
                    for (dx in -1..1) {
                        val yy = y + dy
                        val xx = x + dx
                        // cv2.erode uses BORDER_CONSTANT with +inf for erosion,
                        // so out-of-bounds neighbours do NOT erode the pixel.
                        if (yy in 0 until h && xx in 0 until w && mask.data[yy * w + xx].toInt() == 0) {
                            keep = false
                            break@loop
                        }
                    }
                }
                out[y * w + x] = if (keep && mask.data[y * w + x].toInt() == 1) 1 else 0
            }
        }
        return Mask(w, h, out)
    }

    /**
     * Bilinear resize matching cv2.resize INTER_LINEAR pixel-center alignment:
     * src = (dst + 0.5) * scale - 0.5.
     */
    fun resizeBilinear(src: GrayImage, dstW: Int, dstH: Int): GrayImage {
        val out = FloatArray(dstW * dstH)
        val sx = src.width.toDouble() / dstW
        val sy = src.height.toDouble() / dstH
        for (y in 0 until dstH) {
            val fy = (y + 0.5) * sy - 0.5
            val y0 = kotlin.math.floor(fy).toInt()
            val wy = fy - y0
            val y0c = min(max(y0, 0), src.height - 1)
            val y1c = min(max(y0 + 1, 0), src.height - 1)
            for (x in 0 until dstW) {
                val fx = (x + 0.5) * sx - 0.5
                val x0 = kotlin.math.floor(fx).toInt()
                val wx = fx - x0
                val x0c = min(max(x0, 0), src.width - 1)
                val x1c = min(max(x0 + 1, 0), src.width - 1)
                val top = src.pixels[y0c * src.width + x0c] * (1 - wx) + src.pixels[y0c * src.width + x1c] * wx
                val bot = src.pixels[y1c * src.width + x0c] * (1 - wx) + src.pixels[y1c * src.width + x1c] * wx
                out[y * dstW + x] = (top * (1 - wy) + bot * wy).toFloat()
            }
        }
        return GrayImage(dstW, dstH, out)
    }

    fun resizeBilinearRgb(src: RgbImage, dstW: Int, dstH: Int): RgbImage {
        val out = ByteArray(dstW * dstH * 3)
        val sx = src.width.toDouble() / dstW
        val sy = src.height.toDouble() / dstH
        for (y in 0 until dstH) {
            val fy = (y + 0.5) * sy - 0.5
            val y0 = kotlin.math.floor(fy).toInt()
            val wy = fy - y0
            val y0c = min(max(y0, 0), src.height - 1)
            val y1c = min(max(y0 + 1, 0), src.height - 1)
            for (x in 0 until dstW) {
                val fx = (x + 0.5) * sx - 0.5
                val x0 = kotlin.math.floor(fx).toInt()
                val wx = fx - x0
                val x0c = min(max(x0, 0), src.width - 1)
                val x1c = min(max(x0 + 1, 0), src.width - 1)
                for (c in 0..2) {
                    val p00 = src.pixels[(y0c * src.width + x0c) * 3 + c].toInt() and 0xFF
                    val p01 = src.pixels[(y0c * src.width + x1c) * 3 + c].toInt() and 0xFF
                    val p10 = src.pixels[(y1c * src.width + x0c) * 3 + c].toInt() and 0xFF
                    val p11 = src.pixels[(y1c * src.width + x1c) * 3 + c].toInt() and 0xFF
                    val top = p00 * (1 - wx) + p01 * wx
                    val bot = p10 * (1 - wx) + p11 * wx
                    val v = (top * (1 - wy) + bot * wy).roundToInt()
                    out[(y * dstW + x) * 3 + c] = min(max(v, 0), 255).toByte()
                }
            }
        }
        return RgbImage(dstW, dstH, out)
    }

    /** Area-average resize (cv2 INTER_AREA for downscale). */
    fun resizeArea(src: GrayImage, dstW: Int, dstH: Int): GrayImage {
        val out = FloatArray(dstW * dstH)
        val sx = src.width.toDouble() / dstW
        val sy = src.height.toDouble() / dstH
        for (y in 0 until dstH) {
            val sy0 = y * sy
            val sy1 = (y + 1) * sy
            for (x in 0 until dstW) {
                val sx0 = x * sx
                val sx1 = (x + 1) * sx
                var acc = 0.0
                var area = 0.0
                var yy = kotlin.math.floor(sy0).toInt()
                while (yy < sy1 && yy < src.height) {
                    val hFrac = min(sy1, (yy + 1).toDouble()) - max(sy0, yy.toDouble())
                    var xx = kotlin.math.floor(sx0).toInt()
                    while (xx < sx1 && xx < src.width) {
                        val wFrac = min(sx1, (xx + 1).toDouble()) - max(sx0, xx.toDouble())
                        acc += src.pixels[yy * src.width + xx] * hFrac * wFrac
                        area += hFrac * wFrac
                        xx++
                    }
                    yy++
                }
                out[y * dstW + x] = if (area > 0) (acc / area).toFloat() else 0f
            }
        }
        return GrayImage(dstW, dstH, out)
    }

    /** Gaussian kernel per cv2.getGaussianKernel (sigma<=0 -> 0.3*((k-1)*0.5-1)+0.8). */
    fun gaussianKernel(ksize: Int, sigma: Double): DoubleArray {
        val s = if (sigma <= 0) 0.3 * ((ksize - 1) * 0.5 - 1) + 0.8 else sigma
        val k = DoubleArray(ksize)
        val c = (ksize - 1) / 2.0
        var sum = 0.0
        for (i in 0 until ksize) {
            k[i] = exp(-(i - c) * (i - c) / (2 * s * s))
            sum += k[i]
        }
        for (i in 0 until ksize) k[i] /= sum
        return k
    }

    /** Separable Gaussian blur, reflect-101 borders (cv2.GaussianBlur default). */
    fun gaussianBlur(src: GrayImage, ksize: Int, sigma: Double): GrayImage {
        val k = gaussianKernel(ksize, sigma)
        val r = ksize / 2
        val w = src.width
        val h = src.height
        val tmp = FloatArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                var s = 0.0
                for (i in -r..r) s += k[i + r] * src.pixels[y * w + reflect101(x + i, w)]
                tmp[y * w + x] = s.toFloat()
            }
        }
        val out = FloatArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                var s = 0.0
                for (i in -r..r) s += k[i + r] * tmp[reflect101(y + i, h) * w + x]
                out[y * w + x] = s.toFloat()
            }
        }
        return GrayImage(w, h, out)
    }

    /** 3x3 box filter (cv2.filter2D with ones(3,3)/9), reflect-101 borders. */
    fun boxFilter3(src: GrayImage): GrayImage {
        val w = src.width
        val h = src.height
        val out = FloatArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                var s = 0f
                for (dy in -1..1) {
                    val yy = reflect101(y + dy, h)
                    for (dx in -1..1) {
                        s += src.pixels[yy * w + reflect101(x + dx, w)]
                    }
                }
                out[y * w + x] = s / 9f
            }
        }
        return GrayImage(w, h, out)
    }

    /** numpy-compatible linear-interpolation percentile over all pixels. */
    fun percentile(values: FloatArray, q: Double): Double {
        val sorted = values.copyOf()
        sorted.sort()
        val idx = q / 100.0 * (sorted.size - 1)
        val lo = kotlin.math.floor(idx).toInt()
        val hi = kotlin.math.ceil(idx).toInt()
        if (lo == hi) return sorted[lo].toDouble()
        val frac = idx - lo
        return sorted[lo] * (1 - frac) + sorted[hi] * frac
    }

    fun mean(values: FloatArray): Double {
        var s = 0.0
        for (v in values) s += v
        return s / values.size
    }

    fun std(values: FloatArray): Double {
        val m = mean(values)
        var s = 0.0
        for (v in values) s += (v - m) * (v - m)
        return kotlin.math.sqrt(s / values.size)   // ddof=0, numpy default
    }

    /**
     * BGR(uint8) -> Lab (uint8 scaling) per OpenCV: L*255/100, a+128, b+128.
     * Returns [L, a, b] means are computed by callers; here per-pixel floats.
     */
    fun rgbToLab(r: Int, g: Int, b: Int): FloatArray {
        fun srgbToLinear(v: Double): Double {
            val x = v / 255.0
            return if (x > 0.04045) Math.pow((x + 0.055) / 1.055, 2.4) else x / 12.92
        }
        val rl = srgbToLinear(r.toDouble())
        val gl = srgbToLinear(g.toDouble())
        val bl = srgbToLinear(b.toDouble())
        // D65 sRGB -> XYZ
        var x = 0.412453 * rl + 0.357580 * gl + 0.180423 * bl
        var y = 0.212671 * rl + 0.715160 * gl + 0.072169 * bl
        var z = 0.019334 * rl + 0.119193 * gl + 0.950227 * bl
        x /= 0.950456
        z /= 1.088754
        fun f(t: Double): Double =
            if (t > 0.008856) Math.cbrt(t) else 7.787 * t + 16.0 / 116.0
        val fx = f(x)
        val fy = f(y)
        val fz = f(z)
        val l = if (y > 0.008856) 116.0 * Math.cbrt(y) - 16.0 else 903.3 * y
        val a = 500.0 * (fx - fy) + 128.0
        val bb = 200.0 * (fy - fz) + 128.0
        return floatArrayOf((l * 255.0 / 100.0).toFloat(), a.toFloat(), bb.toFloat())
    }

    /** abs mean of an array. */
    fun meanAbs(values: FloatArray): Double {
        var s = 0.0
        for (v in values) s += abs(v)
        return s / values.size
    }
}
