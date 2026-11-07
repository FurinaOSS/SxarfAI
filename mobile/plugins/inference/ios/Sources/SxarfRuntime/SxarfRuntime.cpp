#include "SxarfRuntime.h"

#include <llama.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <random>
#include <string>
#include <vector>

namespace {

std::mutex runtime_mutex;
llama_model * model = nullptr;
llama_context * context = nullptr;
std::atomic_bool cancelled{false};
std::atomic_bool generating{false};
std::string loaded_path;
uint64_t loaded_size = 0;
uint32_t active_context_length = 0;
bool initialized = false;

void set_error(char * buffer, size_t capacity, const char * message) {
    if (buffer && capacity) {
        std::snprintf(buffer, capacity, "%s", message);
    }
}

size_t valid_utf8_prefix(const std::string & bytes) {
    size_t index = 0;
    while (index < bytes.size()) {
        const auto lead = static_cast<unsigned char>(bytes[index]);
        size_t length = 0;
        if (lead < 0x80) {
            length = 1;
        } else if ((lead & 0xE0) == 0xC0) {
            length = 2;
        } else if ((lead & 0xF0) == 0xE0) {
            length = 3;
        } else if ((lead & 0xF8) == 0xF0) {
            length = 4;
        } else {
            ++index;
            continue;
        }
        if (index + length > bytes.size()) {
            break;
        }
        bool valid = true;
        for (size_t offset = 1; offset < length; ++offset) {
            valid &= (static_cast<unsigned char>(bytes[index + offset]) & 0xC0) == 0x80;
        }
        index += valid ? length : 1;
    }
    return index;
}

void emit_valid_text(std::string & pending, sxarf_token_callback callback, void * callback_context) {
    const size_t count = valid_utf8_prefix(pending);
    if (count && callback) {
        callback(pending.data(), count, callback_context);
        pending.erase(0, count);
    }
}

} // namespace

extern "C" bool sxarf_runtime_initialize(void) {
    std::lock_guard<std::mutex> lock(runtime_mutex);
    if (!initialized) {
        llama_backend_init();
        initialized = true;
    }
    return initialized;
}

extern "C" const char * sxarf_runtime_version(void) {
    return llama_version();
}

extern "C" const char * sxarf_runtime_commit(void) {
    return "cf659f240b232e15700b1721bbb43c1d973c52e9";
}

extern "C" bool sxarf_runtime_supports_gpu(void) {
    return llama_supports_gpu_offload();
}

extern "C" const char * sxarf_runtime_backend(void) {
#if defined(__APPLE__)
    return llama_supports_gpu_offload() ? "Metal" : "CPU";
#elif defined(__ANDROID__) && defined(GGML_USE_VULKAN)
    return llama_supports_gpu_offload() ? "Vulkan" : "CPU";
#else
    return "CPU";
#endif
}

extern "C" int sxarf_model_load(const char * path, uint32_t context_length, int32_t threads,
                                 char * error, size_t error_capacity) {
    std::lock_guard<std::mutex> lock(runtime_mutex);
    if (!initialized) {
        llama_backend_init();
        initialized = true;
    }
    if (!path || !*path || context_length == 0 || threads <= 0) {
        set_error(error, error_capacity, "Invalid model path or load parameters.");
        return -1;
    }
    if (generating.load()) {
        set_error(error, error_capacity, "Cannot load a model while generation is running.");
        return -1;
    }
    if (context) {
        llama_free(context);
        context = nullptr;
    }
    if (model) {
        llama_model_free(model);
        model = nullptr;
    }
    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = llama_supports_gpu_offload() ? 99 : 0;
    model = llama_model_load_from_file(path, model_params);
    if (!model) {
        set_error(error, error_capacity, "llama.cpp could not load this GGUF model.");
        return -1;
    }
    const int32_t trained_context = llama_model_n_ctx_train(model);
    if (trained_context > 0 && context_length > static_cast<uint32_t>(trained_context)) {
        llama_model_free(model);
        model = nullptr;
        set_error(error, error_capacity, "Requested context exceeds the model's trained context.");
        return -1;
    }

    llama_context_params context_params = llama_context_default_params();
    context_params.n_ctx = context_length;
    context_params.n_batch = std::min<uint32_t>(context_length, 512);
    context_params.n_threads = threads;
    context_params.n_threads_batch = threads;
    context = llama_init_from_model(model, context_params);
    if (!context) {
        llama_model_free(model);
        model = nullptr;
        set_error(error, error_capacity, "llama.cpp could not create the model context.");
        return -1;
    }
    loaded_path = path;
    active_context_length = llama_n_ctx(context);
    loaded_size = 0;
    FILE * file = std::fopen(path, "rb");
    if (file) {
        std::fseek(file, 0, SEEK_END);
        const long size = std::ftell(file);
        if (size > 0) loaded_size = static_cast<uint64_t>(size);
        std::fclose(file);
    }
    cancelled.store(false);
    return 0;
}

extern "C" void sxarf_model_unload(void) {
    std::lock_guard<std::mutex> lock(runtime_mutex);
    if (generating.load()) return;
    if (context) {
        llama_free(context);
        context = nullptr;
    }
    if (model) {
        llama_model_free(model);
        model = nullptr;
    }
    loaded_path.clear();
    loaded_size = 0;
    active_context_length = 0;
}

extern "C" bool sxarf_model_is_loaded(void) {
    return model != nullptr && context != nullptr;
}

extern "C" uint64_t sxarf_model_parameter_count(void) {
    return model ? llama_model_n_params(model) : 0;
}

extern "C" uint32_t sxarf_model_context_length(void) {
    return active_context_length;
}

extern "C" uint32_t sxarf_model_trained_context(void) {
      return model ? static_cast<uint32_t>(std::max(0, llama_model_n_ctx_train(model))) : 0;
}

extern "C" uint64_t sxarf_model_file_size(void) {
      return loaded_size;
}

extern "C" const char * sxarf_model_description(void) {
      static char description[256];
      if (!model || llama_model_desc(model, description, sizeof(description)) < 0) {
          description[0] = '\0';
      }
      return description;
}

extern "C" int sxarf_generate(const char * prompt, int32_t max_tokens, float temperature,
                               sxarf_token_callback callback, void * callback_context,
                               char * error, size_t error_capacity) {
    bool expected = false;
    if (!prompt || max_tokens <= 0 || !std::isfinite(temperature) ||
        !generating.compare_exchange_strong(expected, true)) {
        set_error(error, error_capacity, "Invalid generation request or another generation is active.");
        return -1;
    }
    cancelled.store(false);
    std::unique_lock<std::mutex> lock(runtime_mutex);
    if (!model || !context) {
        generating.store(false);
        set_error(error, error_capacity, "Load a model before generating.");
        return -1;
    }
    auto * active_model = model;
    auto * active_context = context;
    lock.unlock();

    struct GenerationGuard {
        ~GenerationGuard() { generating.store(false); }
    } guard;

    const llama_vocab * vocab = llama_model_get_vocab(active_model);
    const auto prompt_length = std::strlen(prompt);
    if (prompt_length > static_cast<size_t>(INT32_MAX)) {
        set_error(error, error_capacity, "Prompt is too large.");
        return -1;
    }
    const int32_t needed = -llama_tokenize(vocab, prompt, static_cast<int32_t>(prompt_length),
                                           nullptr, 0, true, true);
    if (needed <= 0 || static_cast<uint32_t>(needed) >= active_context_length) {
        set_error(error, error_capacity, "Prompt does not fit in the active context.");
        return -1;
    }
    std::vector<llama_token> prompt_tokens(static_cast<size_t>(needed));
    const int32_t prompt_count = llama_tokenize(vocab, prompt, static_cast<int32_t>(prompt_length),
                                                prompt_tokens.data(), needed, true, true);
    if (prompt_count < 0) {
        set_error(error, error_capacity, "Could not tokenize the prompt.");
        return -1;
    }
    llama_memory_clear(llama_get_memory(active_context), true);
    const int32_t batch_limit = static_cast<int32_t>(llama_n_batch(active_context));
    if (batch_limit <= 0) {
        set_error(error, error_capacity, "The model context has an invalid batch size.");
        return -1;
    }
    for (int32_t offset = 0; offset < prompt_count; offset += batch_limit) {
        if (cancelled.load()) return 1;
        const int32_t count = std::min(batch_limit, prompt_count - offset);
        llama_batch batch = llama_batch_get_one(prompt_tokens.data() + offset, count);
        if (llama_decode(active_context, batch) != 0) {
            set_error(error, error_capacity, "llama.cpp failed to evaluate the prompt.");
            return -1;
        }
    }

    auto sampler_params = llama_sampler_chain_default_params();
    llama_sampler * sampler = llama_sampler_chain_init(sampler_params);
    if (!sampler) {
        set_error(error, error_capacity, "Could not initialize the sampler.");
        return -1;
    }
    if (temperature <= 0.001f) {
        llama_sampler_chain_add(sampler, llama_sampler_init_greedy());
    } else {
        llama_sampler_chain_add(sampler, llama_sampler_init_top_k(40));
        llama_sampler_chain_add(sampler, llama_sampler_init_top_p(0.95f, 1));
        llama_sampler_chain_add(sampler, llama_sampler_init_temp(temperature));
        std::random_device device;
        llama_sampler_chain_add(sampler, llama_sampler_init_dist(device()));
    }

    std::string pending;
    const int32_t token_limit = std::min<int32_t>(
        max_tokens,
        static_cast<int32_t>(active_context_length) - prompt_count);
    int32_t generated = 0;
    int result = 0;
    while (generated < token_limit && !cancelled.load()) {
        const llama_token token = llama_sampler_sample(sampler, active_context, -1);
        llama_sampler_accept(sampler, token);
        if (llama_vocab_is_eog(vocab, token)) break;
        char buffer[256];
        const int32_t piece_length = llama_token_to_piece(vocab, token, buffer, sizeof(buffer), 0, true);
        if (piece_length < 0) {
            set_error(error, error_capacity, "Could not decode a generated token.");
            result = -1;
            break;
        }
        pending.append(buffer, static_cast<size_t>(piece_length));
        emit_valid_text(pending, callback, callback_context);
        ++generated;
        if (generated < token_limit) {
            llama_token next_token = token;
            llama_batch batch = llama_batch_get_one(&next_token, 1);
            if (llama_decode(active_context, batch) != 0) {
                set_error(error, error_capacity, "llama.cpp failed during token generation.");
                result = -1;
                break;
            }
        }
    }
    if (!pending.empty() && callback) callback(pending.data(), pending.size(), callback_context);
    llama_sampler_free(sampler);
    if (cancelled.load()) return 1;
    return result;
}

extern "C" void sxarf_cancel_generation(void) {
    cancelled.store(true);
}
