#ifndef SXARF_RUNTIME_H
#define SXARF_RUNTIME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*sxarf_token_callback)(const char *text, size_t length, void *context);

bool sxarf_runtime_initialize(void);
const char *sxarf_runtime_version(void);
const char *sxarf_runtime_commit(void);
bool sxarf_runtime_supports_gpu(void);
const char *sxarf_runtime_backend(void);
int sxarf_model_load(const char *path, uint32_t context_length, int32_t threads,
                     char *error, size_t error_capacity);
void sxarf_model_unload(void);
bool sxarf_model_is_loaded(void);
uint64_t sxarf_model_parameter_count(void);
uint32_t sxarf_model_context_length(void);
uint32_t sxarf_model_trained_context(void);
uint64_t sxarf_model_file_size(void);
const char * sxarf_model_description(void);
int sxarf_generate(const char *prompt, int32_t max_tokens, float temperature,
                   sxarf_token_callback callback, void *context,
                   char *error, size_t error_capacity);
void sxarf_cancel_generation(void);

#ifdef __cplusplus
}
#endif

#endif
