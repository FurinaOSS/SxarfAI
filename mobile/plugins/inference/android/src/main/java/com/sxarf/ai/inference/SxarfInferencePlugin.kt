package com.sxarf.ai.inference

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.StatFs
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONArray
import org.json.JSONObject

@CapacitorPlugin(name = "SxarfInference")
class SxarfInferencePlugin : Plugin() {
    private val native = NativeRuntime()
    private val executor = Executors.newFixedThreadPool(2)
    private val generating = AtomicBoolean(false)
    @Volatile private var loadedModelId: String? = null

    private val modelsDirectory: File
        get() = File(context.noBackupFilesDir, "models")

    override fun load() {
        modelsDirectory.mkdirs()
    }

    @PluginMethod
    fun initialize(call: PluginCall) {
        try {
            if (!native.initialize()) {
                call.reject("llama.cpp runtime initialization failed.")
                return
            }
            val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val memory = ActivityManager.MemoryInfo()
            activityManager.getMemoryInfo(memory)
            val storage = StatFs(context.noBackupFilesDir.path)
            val result = JSObject()
            result.put("runtime", "llama.cpp")
            result.put("version", native.version())
            result.put("commit", native.commit())
            result.put("backend", native.backend())
            result.put("gpuAvailable", native.gpuAvailable())
            result.put("platform", "Android ${Build.VERSION.RELEASE}")
            result.put("totalMemoryBytes", memory.totalMem)
            result.put("availableMemoryBytes", memory.availMem)
            result.put("availableStorageBytes", storage.availableBytes)
            call.resolve(result)
        } catch (error: Exception) {
            call.reject("Could not initialize the on-device inference runtime.", error)
        }
    }

    @PluginMethod
    fun listModels(call: PluginCall) {
        try {
            val installed = readInstalledModels()
            val models = JSArray()
            for (record in installed) {
                val file = File(modelsDirectory, record.getString("filename"))
                if (!file.isFile || file.length() != record.optLong("sizeBytes")) continue
                models.put(JSObject().apply {
                    put("id", record.getString("id"))
                    put("path", file.absolutePath)
                    put("sizeBytes", file.length())
                })
            }
            call.resolve(JSObject().put("models", models))
        } catch (error: Exception) {
            call.reject("Could not read the installed-model list.", error)
        }
    }

    @PluginMethod
    fun downloadModel(call: PluginCall) {
        val id = call.getString("id")
        val filename = call.getString("filename")
        val source = call.getString("url")
        val sha256 = call.getString("sha256")
        val sizeBytes = call.getLong("sizeBytes")
        if (!validId(id) || !validFilename(filename) || !validUrl(source) ||
            !validSha256(sha256) || sizeBytes == null || sizeBytes <= 0) {
            call.reject("The model download metadata is invalid.")
            return
        }
        executor.execute {
            val temporary = File(modelsDirectory, "$id.download")
            try {
                modelsDirectory.mkdirs()
                download(source!!, temporary, id!!, sizeBytes, sha256!!)
                if (temporary.length() != sizeBytes) throw IllegalStateException("Model size does not match the catalog.")
                val destination = File(modelsDirectory, filename!!)
                if (destination.exists() && !destination.delete()) {
                    throw IllegalStateException("Could not replace the existing model file.")
                }
                if (!temporary.renameTo(destination)) {
                    throw IllegalStateException("Could not install the verified model file.")
                }
                val installed = readInstalledModels().filterNot { it.optString("id") == id }.toMutableList()
                installed.add(JSONObject().put("id", id).put("filename", filename)
                    .put("sizeBytes", sizeBytes).put("sha256", sha256.lowercase()))
                writeInstalledModels(installed)
                notifyDownload(id, sizeBytes, sizeBytes, "complete")
                call.resolve(JSObject().put("id", id).put("path", destination.absolutePath)
                    .put("sizeBytes", sizeBytes))
            } catch (error: Exception) {
                temporary.delete()
                notifyDownload(id!!, 0, sizeBytes, "failed")
                call.reject("Model download or checksum verification failed: ${error.message}", error)
            }
        }
    }

    @PluginMethod
    fun deleteModel(call: PluginCall) {
        val id = call.getString("id")
        if (!validId(id)) {
            call.reject("A valid model ID is required.")
            return
        }
        if (generating.get()) {
            call.reject("Stop generation before deleting a model.")
            return
        }
        if (loadedModelId == id) {
            call.reject("Unload the model before deleting it.")
            return
        }
        try {
            val records = readInstalledModels()
            val record = records.firstOrNull { it.optString("id") == id }
            if (record != null) {
                val file = File(modelsDirectory, record.getString("filename"))
                if (file.exists() && !file.delete()) throw IllegalStateException("Could not delete the model file.")
                writeInstalledModels(records.filterNot { it.optString("id") == id })
            }
            call.resolve()
        } catch (error: Exception) {
            call.reject("Could not delete the model.", error)
        }
    }

    @PluginMethod
    fun loadModel(call: PluginCall) {
        val id = call.getString("id")
        val requestedContext = call.getInt("contextLength")
        val requestedThreads = call.getInt("threads")
        if (!validId(id) || requestedContext == null || requestedContext <= 0 ||
            requestedThreads == null || requestedThreads <= 0) {
            call.reject("The model load options are invalid.")
            return
        }
        if (generating.get()) {
            call.reject("Stop generation before switching models.")
            return
        }
        executor.execute {
            try {
                val record = readInstalledModels().firstOrNull { it.optString("id") == id }
                    ?: throw IllegalStateException("The model is not installed on this device.")
                val file = File(modelsDirectory, record.getString("filename"))
                if (!file.isFile || file.length() != record.optLong("sizeBytes")) {
                    throw IllegalStateException("The installed model file is missing or incomplete.")
                }
                val error = native.loadModel(file.absolutePath, requestedContext, requestedThreads.coerceIn(1, 8))
                if (error.isNotEmpty()) throw IllegalStateException(error)
                loadedModelId = id
                val info = JSObject()
                info.put("id", id)
                info.put("description", native.description())
                info.put("sizeBytes", native.modelSize())
                info.put("parameterCount", native.parameterCount())
                info.put("trainedContext", native.trainedContext())
                info.put("activeContext", native.contextLength())
                info.put("backend", native.backend())
                info.put("processMemoryBytes", residentMemoryBytes())
                call.resolve(info)
            } catch (error: Exception) {
                call.reject("Could not load the model: ${error.message}", error)
            }
        }
    }

    @PluginMethod
    fun unloadModel(call: PluginCall) {
        if (generating.get()) {
            call.reject("Stop generation before unloading the model.")
            return
        }
        native.unloadModel()
        loadedModelId = null
        call.resolve()
    }

    @PluginMethod
    fun generate(call: PluginCall) {
        val prompt = call.getString("prompt")
        val maxTokens = call.getInt("maxTokens")
        val temperature = call.getDouble("temperature")
        if (prompt.isNullOrEmpty() || maxTokens == null || maxTokens <= 0 || temperature == null) {
            call.reject("The generation options are invalid.")
            return
        }
        if (loadedModelId == null) {
            call.reject("Load a model before generating.")
            return
        }
        if (!generating.compareAndSet(false, true)) {
            call.reject("Generation is already running.")
            return
        }
        executor.execute {
            val output = StringBuilder()
            try {
                val callback = object : NativeRuntime.TokenCallback {
                    override fun onTokenBytes(bytes: ByteArray) {
                        val token = String(bytes, Charsets.UTF_8)
                        output.append(token)
                        val event = JSObject().put("token", token)
                        notifyListeners("token", event)
                    }
                }
                val result = native.generate(
                    prompt.toByteArray(Charsets.UTF_8),
                    maxTokens.coerceAtMost(4096),
                    temperature.toFloat().coerceIn(0f, 2f),
                    callback
                )
                if (result < 0) {
                    call.reject(native.lastError().ifEmpty { "llama.cpp generation failed." })
                } else {
                    call.resolve(JSObject().put("text", output.toString()).put("cancelled", result == 1))
                }
            } catch (error: Exception) {
                call.reject("llama.cpp generation failed.", error)
            } finally {
                generating.set(false)
            }
        }
    }

    @PluginMethod
    fun cancelGeneration(call: PluginCall) {
        native.cancel()
        call.resolve()
    }

    private fun download(source: String, destination: File, id: String, expectedSize: Long, expectedSha256: String) {
        val connection = URL(source).openConnection() as HttpURLConnection
        connection.connectTimeout = 30_000
        connection.readTimeout = 60_000
        connection.instanceFollowRedirects = true
        try {
            connection.connect()
            if (connection.url.protocol != "https") throw IllegalStateException("Model downloads must remain on HTTPS.")
            if (connection.responseCode !in 200..299) throw IllegalStateException("Model server returned HTTP ${connection.responseCode}.")
            val input = connection.inputStream
            val digest = MessageDigest.getInstance("SHA-256")
            var received = 0L
            var lastPercent = -1L
            notifyDownload(id, received, expectedSize, "downloading")
            input.use { stream ->
                FileOutputStream(destination).use { output ->
                    val buffer = ByteArray(1024 * 256)
                    while (true) {
                        val count = stream.read(buffer)
                        if (count < 0) break
                        received += count
                        if (received > expectedSize) throw IllegalStateException("Model download exceeds its catalog size.")
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                        val percent = received * 100 / expectedSize
                        if (percent != lastPercent || received == expectedSize) {
                            notifyDownload(id, received, expectedSize, "downloading")
                            lastPercent = percent
                        }
                    }
                }
            }
            if (received != expectedSize) throw IllegalStateException("Model size does not match the catalog.")
            notifyDownload(id, received, expectedSize, "verifying")
            val actualHash = digest.digest().joinToString("") { "%02x".format(it) }
            if (actualHash != expectedSha256.lowercase()) {
                throw IllegalStateException("Model SHA-256 does not match the catalog.")
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun notifyDownload(id: String, received: Long, total: Long, state: String) {
        notifyListeners("downloadProgress", JSObject().apply {
            put("modelId", id)
            put("receivedBytes", received)
            put("totalBytes", total)
            put("state", state)
        })
    }

    private fun readInstalledModels(): List<JSONObject> {
        val preferences = context.getSharedPreferences("sxarf-models", Context.MODE_PRIVATE)
        val value = preferences.getString("installed", null) ?: return emptyList()
        val array = JSONArray(value)
        return (0 until array.length()).map { array.getJSONObject(it) }
    }

    private fun writeInstalledModels(models: List<JSONObject>) {
        val array = JSONArray()
        models.forEach(array::put)
        check(context.getSharedPreferences("sxarf-models", Context.MODE_PRIVATE).edit()
            .putString("installed", array.toString()).commit()) { "Could not persist installed-model metadata." }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun residentMemoryBytes(): Long {
        val line = File("/proc/self/status").useLines { lines -> lines.firstOrNull { it.startsWith("VmRSS:") } }
        return line?.substringAfter(':')?.trim()?.substringBefore(' ')?.toLongOrNull()?.times(1024) ?: 0L
    }

    private fun validId(value: String?): Boolean = value?.matches(Regex("[a-z0-9][a-z0-9-]{0,80}")) == true
    private fun validFilename(value: String?): Boolean =
        value?.matches(Regex("[A-Za-z0-9._-]+\\.gguf")) == true
    private fun validSha256(value: String?): Boolean = value?.matches(Regex("[a-fA-F0-9]{64}")) == true
    private fun validUrl(value: String?): Boolean =
        value?.let { runCatching { URL(it).protocol == "https" && URL(it).host == "huggingface.co" }.getOrDefault(false) } == true
}
