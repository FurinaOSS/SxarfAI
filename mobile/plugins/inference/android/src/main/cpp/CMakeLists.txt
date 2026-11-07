cmake_minimum_required(VERSION 3.22.1)
project(sxarf_inference LANGUAGES C CXX)

option(SXARF_ANDROID_VULKAN "Build the llama.cpp Vulkan backend" OFF)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_VULKAN ${SXARF_ANDROID_VULKAN} CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_MTMD OFF CACHE BOOL "" FORCE)

add_subdirectory(
    ${CMAKE_CURRENT_LIST_DIR}/../../../../../../native/llama.cpp
    ${CMAKE_CURRENT_BINARY_DIR}/llama
)

add_library(sxarf_runtime SHARED
    ${CMAKE_CURRENT_LIST_DIR}/../../../../ios/Sources/SxarfRuntime/SxarfRuntime.cpp
    sxarf_jni.cpp
)
target_include_directories(sxarf_runtime PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/../../../../ios/Sources/SxarfRuntime/include
)
target_link_libraries(sxarf_runtime PRIVATE llama android log)
if(SXARF_ANDROID_VULKAN)
    target_compile_definitions(sxarf_runtime PRIVATE GGML_USE_VULKAN)
endif()
