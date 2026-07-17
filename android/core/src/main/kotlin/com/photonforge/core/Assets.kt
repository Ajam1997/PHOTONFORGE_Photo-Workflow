package com.photonforge.core

import com.photonforge.core.fusion.ScoreFusion
import com.photonforge.core.genre.GenreRouter
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.float
import kotlinx.serialization.json.jsonPrimitive

/**
 * Loads the assets exported by android/tools/export_assets.py from classpath
 * resources (photonforge/{weights,adapter,prototypes}.json). These are the same
 * numbers the desktop runtime reads from genre_weights.db — one source of truth.
 */
object Assets {

    private fun readResource(name: String): String {
        val stream = Assets::class.java.classLoader.getResourceAsStream("photonforge/$name")
            ?: error("missing bundled asset photonforge/$name")
        return stream.bufferedReader().readText()
    }

    fun loadWeightProfiles(text: String = readResource("weights.json")): ScoreFusion.WeightProfiles {
        val root = Json.parseToJsonElement(text).jsonObject
        fun axis(name: String): Map<String, Map<String, Double>> =
            root.getValue(name).jsonObject.mapValues { (_, profile) ->
                profile.jsonObject.mapValues { it.value.jsonPrimitive.double }
            }
        return ScoreFusion.WeightProfiles(subject = axis("subject"), type = axis("type"))
    }

    fun loadAdapter(text: String = readResource("adapter.json")): GenreRouter.Adapter {
        val root = Json.parseToJsonElement(text).jsonObject
        fun head(name: String): GenreRouter.LinearHead? {
            val obj = root[name]?.jsonObject ?: return null
            val classes = obj.getValue("classes").jsonArray.map { it.jsonPrimitive.content }
            val weight = obj.getValue("weight").jsonArray.map { row ->
                FloatArray(row.jsonArray.size) { i -> row.jsonArray[i].jsonPrimitive.float }
            }.toTypedArray()
            val bias = obj.getValue("bias").jsonArray.let { arr ->
                FloatArray(arr.size) { i -> arr[i].jsonPrimitive.float }
            }
            return GenreRouter.LinearHead(classes, weight, bias)
        }
        return GenreRouter.Adapter(subject = head("subject"), type = head("type"))
    }

    fun loadPrototypes(text: String = readResource("prototypes.json")): GenreRouter.Prototypes {
        val root = Json.parseToJsonElement(text).jsonObject
        val rows = root.getValue("rows").jsonArray.map { row ->
            FloatArray(row.jsonArray.size) { i -> row.jsonArray[i].jsonPrimitive.float }
        }.toTypedArray()
        return GenreRouter.Prototypes(rows)
    }
}
