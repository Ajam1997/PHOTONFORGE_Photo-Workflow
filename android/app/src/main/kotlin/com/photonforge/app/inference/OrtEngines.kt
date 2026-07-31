package com.photonforge.app.inference

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer

/**
 * The acceleration seam from android-port-brief.md §7.4: pipeline code asks the
 * registry for an engine per model and never imports one directly. Phase 2
 * ships CPU/XNNPACK only; a Pixel 11 NPU engine slots in behind [InferenceEngine]
 * with automatic CPU fallback in [EngineRegistry.load].
 */
interface InferenceEngine {
    val name: String
    fun load(modelBytes: ByteArray): Session
    interface Session : AutoCloseable {
        /** Run with a single float input; returns the first output as (shape, data). */
        fun run(input: FloatArray, shape: LongArray): Pair<LongArray, FloatArray>
        val inputShape: LongArray?
    }
}

class OrtCpuEngine : InferenceEngine {
    override val name = "ort-cpu-xnnpack"
    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()

    override fun load(modelBytes: ByteArray): InferenceEngine.Session {
        val options = OrtSession.SessionOptions()
        options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
        val session = env.createSession(modelBytes, options)
        return OrtSessionWrapper(env, session)
    }

    private class OrtSessionWrapper(
        val env: OrtEnvironment,
        val session: OrtSession,
    ) : InferenceEngine.Session {

        override val inputShape: LongArray? = try {
            val info = session.inputInfo.values.first().info
            (info as? ai.onnxruntime.TensorInfo)?.shape
        } catch (e: Exception) {
            null
        }

        override fun run(input: FloatArray, shape: LongArray): Pair<LongArray, FloatArray> {
            val inputName = session.inputNames.first()
            OnnxTensor.createTensor(env, FloatBuffer.wrap(input), shape).use { tensor ->
                session.run(mapOf(inputName to tensor)).use { results ->
                    val out = results[0] as OnnxTensor
                    val outShape = out.info.shape
                    val buf = out.floatBuffer
                    val data = FloatArray(buf.remaining())
                    buf.get(data)
                    return outShape to data
                }
            }
        }

        override fun close() = session.close()
    }
}

/** Per-model engine preference with automatic CPU fallback (§7.4). */
class EngineRegistry(private val cpu: InferenceEngine = OrtCpuEngine()) {

    private val extra = mutableMapOf<String, InferenceEngine>()
    private val preferences = mutableMapOf<String, List<String>>()
    var onFallback: ((model: String, engine: String, error: Throwable) -> Unit)? = null

    fun register(engine: InferenceEngine) { extra[engine.name] = engine }
    fun prefer(model: String, engines: List<String>) { preferences[model] = engines }

    fun load(model: String, bytes: ByteArray): InferenceEngine.Session {
        for (name in preferences[model].orEmpty()) {
            val engine = extra[name] ?: continue
            try {
                return engine.load(bytes)
            } catch (e: Throwable) {
                onFallback?.invoke(model, name, e)
            }
        }
        return cpu.load(bytes)
    }
}
