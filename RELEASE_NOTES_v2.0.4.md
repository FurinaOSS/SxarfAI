# Sxarf AI — V2.0.4
**Your AI. Your Hardware. Your Control.**
Introducing Sxarf AI V2.0.4: a completely local AI assistant built to make powerful AI accessible to everyone. No expensive servers. No mandatory cloud inference. No need for a high-end workstation. Designed to bring local AI to everyday computers, including older and lower-end hardware.

## What's New in V2.0.4

### Performance
- Streaming replies now keep completed Markdown blocks instead of parsing and rendering the entire response on every update. Only the unfinished final block is refreshed; an open code block appends new text. Mouse and scroll handling is throttled, and observers avoid unnecessary work during streaming. Animations and visual effects are unchanged.
- In a synthetic UI benchmark using a 15,000-character streamed reply in headless Chromium with software rendering, layout time dropped from about 9.5 seconds to 0.7 seconds and script time from about 3.2 seconds to 0.5 seconds. This is a synthetic UI benchmark, not a model-speed benchmark.

### UI
- The macOS model menu now identifies DeepSeek-R1-Distill-Qwen-1.5B-abliterated as the coding model.
- Both installers now package a minified frontend HTML/CSS bundle. Inline JavaScript and app behavior are unchanged.

### Backend
- Selecting the coding model downloads and imports its Q4_K_M GGUF into the local Ollama service and supports streamed replies. Ollama itself must already be installed; Sxarf AI does not install the Ollama application.

### Windows
- The Windows x64 NSIS installer is rebuilt for V2.0.4 and named `SxarfAI-2.0.4-win-x64.exe`. The existing Windows CPU backend and supported-model setup are retained.

### macOS
- The Apple Silicon arm64 DMG is rebuilt for V2.0.4 and named `SxarfAI-2.0.4-mac.dmg`. It retains the Apple MLX backend.

### Fixes
- The streaming-rendering change above addresses the increasing UI lag during longer generated replies. No additional behavior fixes could be confirmed from the available release evidence.

## Lightweight by Design
- Runs with under 5 GB of RAM in supported configurations.
- No cloud inference required; AI processing happens locally on your hardware.
- Designed with accessibility and performance in mind.

## Windows Installation
Available as a downloadable .exe installer. 1) Download it from the Assets section. 2) Open the .exe. 3) Follow the installation instructions. 4) Launch Sxarf AI. 5) On first launch it checks available disk space and prepares the required environment and AI models. 6) When setup finishes, start chatting. Note: first launch may take longer because the required models are downloaded; time depends on internet speed.

## Optimized for Apple Silicon
The macOS .dmg release includes additional optimizations using Apple's MLX framework, which takes advantage of Apple Silicon's unified memory for efficient local inference.

## Real-World Performance Benchmarks

### macOS — MacBook Neo

| Model | Backend | Generation speed | RAM |
|---|---|---:|---:|
| Gemma 2 2B | Apple MLX | ~30 tokens/s | ~2.5 GB |

### Windows 11 — ASUS Vivobook S 14 OLED

| Model | Backend | RAM idle | RAM during generation | Generation speed |
|---|---|---:|---:|---:|
| Gemma 2 2B | CPU | ~150 MB | ~263 MB | ~3.5 tokens/s |

### Platform Comparison

| Metric | macOS | Windows 11 |
|---|---:|---:|
| Model | Gemma 2 2B | Gemma 2 2B |
| Inference | Apple MLX | CPU |
| Generation speed | ~30 tokens/s | ~3.5 tokens/s |
| RAM during generation | ~2.5 GB | ~263 MB |

macOS is about 8.6x faster in generation speed; Windows reports much lower RAM usage.

Benchmarks are approximate and vary with hardware, model configuration, memory accounting and system conditions. RAM figures should not be read as total model memory requirements unless measured across the whole application and inference process.

## Windows 11 Support
Dedicated Windows 11 support through the .exe installer.
First-launch setup automatically downloads and prepares five supported models: SmolLM2, SmolLM3, Llama 3.2, Gemma 2, Phi 3.5. Total download is about 9 GB. LFM and Stable Code are excluded from the Windows build. Only the currently selected model stays loaded, reducing memory usage when switching models.
Windows Research Agents: web search, source extraction, source citations, automatic research mode, always-on research mode, disabled research mode.
Windows performance optimizations: automatic CPU thread and batch-size tuning, memory-mapped model loading, optimized model memory usage, Windows-compatible research-agent execution, native Windows GPU acceleration for the application interface.
Important: AI inference currently runs on the CPU. GPU acceleration applies to the application interface, not AI generation.

## Available Builds
- Windows: .exe installer for Windows 11.
- macOS: .dmg installer with Apple MLX optimizations.
- Linux: planned for a future release.

## Mobile and iPadOS Status
Mobile support is not part of the V2.0.4 release, and there is no iOS, iPadOS, or Android installer in these builds. A separate V2.1 mobile development foundation is being built with a Capacitor interface and native llama.cpp bridges for iOS and Android. The iPhone simulator app has been built and launched, and the native runtime bridge initializes; GGUF model inference has not yet been verified. No physical-device testing, Android build, signed IPA, or APK is claimed. See [mobile/README.md](./mobile/README.md) for implementation status and remaining limitations.

## The Goal
AI should be accessible to everyone, not just people with expensive hardware. The goal is to make local AI practical without expensive hardware, cloud subscriptions, or sending conversations to external AI servers. This is only the beginning.

Thank you for checking out Sxarf AI V2.0.x! / **Sxarf AI — Your AI. Your Hardware. Your Control.**
