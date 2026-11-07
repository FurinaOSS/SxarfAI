#include "SxarfRuntime.h"

#include <jni.h>

#include <limits>
#include <string>

namespace {

std::string java_string(JNIEnv * env, jstring value) {
    if (!value) return {};
    const char * chars = env->GetStringUTFChars(value, nullptr);
    if (!chars) return {};
    std::string result(chars);
    env->ReleaseStringUTFChars(value, chars);
    return result;
}

struct TokenSink {
    JNIEnv * env;
    jobject callback;
    jmethodID method;
};

thread_local std::string generation_error;

void on_token(const char * text, size_t length, void * context) {
    auto * sink = static_cast<TokenSink *>(context);
    if (!sink || !sink->env || !sink->callback || !sink->method ||
        length > static_cast<size_t>(std::numeric_limits<jsize>::max())) return;
    jbyteArray bytes = sink->env->NewByteArray(static_cast<jsize>(length));
    if (!bytes) return;
    sink->env->SetByteArrayRegion(bytes, 0, static_cast<jsize>(length),
                                 reinterpret_cast<const jbyte *>(text));
    sink->env->CallVoidMethod(sink->callback, sink->method, bytes);
    sink->env->DeleteLocalRef(bytes);
}

} // namespace

extern "C" JNIEXPORT jboolean JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_initialize(JNIEnv *, jobject) {
    return sxarf_runtime_initialize() ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_backend(JNIEnv * env, jobject) {
    return env->NewStringUTF(sxarf_runtime_backend());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_version(JNIEnv * env, jobject) {
    return env->NewStringUTF(sxarf_runtime_version());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_commit(JNIEnv * env, jobject) {
    return env->NewStringUTF(sxarf_runtime_commit());
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_gpuAvailable(JNIEnv *, jobject) {
    return sxarf_runtime_supports_gpu() ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_loadModel(
    JNIEnv * env, jobject, jstring path, jint context_length, jint threads
) {
    std::string model_path = java_string(env, path);
    char error[512] = {};
    const int result = sxarf_model_load(
        model_path.c_str(), static_cast<uint32_t>(context_length),
        static_cast<int32_t>(threads), error, sizeof(error)
    );
    return env->NewStringUTF(result == 0 ? "" : error);
}

extern "C" JNIEXPORT void JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_unloadModel(JNIEnv *, jobject) {
    sxarf_model_unload();
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_modelIsLoaded(JNIEnv *, jobject) {
    return sxarf_model_is_loaded() ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_parameterCount(JNIEnv *, jobject) {
    return static_cast<jlong>(sxarf_model_parameter_count());
}

extern "C" JNIEXPORT jint JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_contextLength(JNIEnv *, jobject) {
    return static_cast<jint>(sxarf_model_context_length());
}

extern "C" JNIEXPORT jint JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_trainedContext(JNIEnv *, jobject) {
    return static_cast<jint>(sxarf_model_trained_context());
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_modelSize(JNIEnv *, jobject) {
    return static_cast<jlong>(sxarf_model_file_size());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_description(JNIEnv * env, jobject) {
    return env->NewStringUTF(sxarf_model_description());
}

extern "C" JNIEXPORT jint JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_generate(
    JNIEnv * env, jobject, jbyteArray prompt, jint max_tokens, jfloat temperature, jobject callback
) {
    if (!prompt || !callback) return -1;
    const jsize length = env->GetArrayLength(prompt);
    std::string prompt_text(static_cast<size_t>(length), '\0');
    env->GetByteArrayRegion(prompt, 0, length, reinterpret_cast<jbyte *>(prompt_text.data()));
    jclass callback_class = env->GetObjectClass(callback);
    jmethodID method = callback_class
        ? env->GetMethodID(callback_class, "onTokenBytes", "([B)V")
        : nullptr;
    if (!method) {
        if (callback_class) env->DeleteLocalRef(callback_class);
        return -1;
    }
    TokenSink sink{env, callback, method};
    char error[512] = {};
    const int result = sxarf_generate(
        prompt_text.c_str(), max_tokens, temperature, on_token, &sink, error, sizeof(error)
    );
    generation_error = error;
    env->DeleteLocalRef(callback_class);
    return result;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_lastError(JNIEnv * env, jobject) {
    return env->NewStringUTF(generation_error.c_str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_sxarf_ai_inference_NativeRuntime_cancel(JNIEnv *, jobject) {
    sxarf_cancel_generation();
}
