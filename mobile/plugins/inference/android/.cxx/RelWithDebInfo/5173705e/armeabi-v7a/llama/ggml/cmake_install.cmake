# Install script for directory: /Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/usr/local")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "RelWithDebInfo")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "0")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "TRUE")
endif()

# Set default install directory permissions.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/Users/asimlatif/Library/Android/sdk/ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-objdump")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("/Users/asimlatif/Downloads/proj/mobile/plugins/inference/android/.cxx/RelWithDebInfo/5173705e/armeabi-v7a/llama/ggml/src/cmake_install.cmake")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/Users/asimlatif/Downloads/proj/mobile/plugins/inference/android/.cxx/RelWithDebInfo/5173705e/armeabi-v7a/llama/ggml/src/libggml.a")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE FILE FILES
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-cpu.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-alloc.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-backend.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-blas.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-cann.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-cpp.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-cuda.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-opt.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-metal.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-rpc.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-virtgpu.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-sycl.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-vulkan.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-webgpu.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-zendnn.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/ggml-openvino.h"
    "/Users/asimlatif/Downloads/proj/mobile/native/llama.cpp/ggml/include/gguf.h"
    )
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/Users/asimlatif/Downloads/proj/mobile/plugins/inference/android/.cxx/RelWithDebInfo/5173705e/armeabi-v7a/llama/ggml/src/libggml-base.a")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/ggml" TYPE FILE FILES
    "/Users/asimlatif/Downloads/proj/mobile/plugins/inference/android/.cxx/RelWithDebInfo/5173705e/armeabi-v7a/llama/ggml/ggml-config.cmake"
    "/Users/asimlatif/Downloads/proj/mobile/plugins/inference/android/.cxx/RelWithDebInfo/5173705e/armeabi-v7a/llama/ggml/ggml-config-version.cmake"
    )
endif()

