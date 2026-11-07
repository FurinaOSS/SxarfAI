package com.sxarf.ai.inference

internal class NativeRuntime {
    external fun initialize(): Boolean
    external fun backend(): String
    external fun version(): String
    external fun commit(): String
    external fun gpuAvailable(): Boolean
    external fun loadModel(path: String, contextLength: Int, threads: Int): String
    external fun unloadModel()
    external fun modelIsLoaded(): Boolean
    external fun parameterCount(): Long
    external fun contextLength(): Int
    external fun trainedContext(): Int
    external fun modelSize(): Long
    external fun description(): String
    external fun generate(prompt: ByteArray, maxTokens: Int, temperature: Float, callback: TokenCallback): Int
    external fun lastError(): String
    external fun cancel()

    interface TokenCallback {
        fun onTokenBytes(bytes: ByteArray)
    }

    companion object {
        init {
            System.loadLibrary("sxarf_runtime")
        }
    }
}
