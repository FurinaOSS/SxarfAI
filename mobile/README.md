# Sxarf AI Mobile — Compatibility Assessment and Architecture

## Status

Phases 1 and 2 (compatibility assessment and architecture selection) remain
documented below. A separate v2.1 mobile development foundation now exists in
this directory. It does not replace or alter the macOS and Windows entry points,
and it is not included in the v2.0.4 desktop release.

The current state is a development foundation, not a feature-complete mobile
release: the iOS simulator app builds and launches, and its native llama.cpp
bridge initializes. Model loading/generation/cancellation have not yet been
verified with a GGUF fixture on the simulator. No physical device or Android
build has been tested.

## Phase 3: Mobile foundation implemented

- Capacitor 8.6.0 app and independent Vite/TypeScript frontend under `mobile/`,
  with responsive phone and tablet layouts and native-safe-area styling.
- Typed Capacitor inference plugin with iOS Swift/C++ and Android Kotlin/JNI
  implementations. Both use the pinned llama.cpp revision
  `cf659f240b232e15700b1721bbb43c1d973c52e9`.
- iOS llama.cpp XCFramework build script for arm64 devices and arm64/x86_64
  simulators; the Xcode app is configured for iOS 16.4 and newer.
- On-device model catalog currently contains TinyLlama 1.1B Chat Q4_K_M.
  Models are user-initiated downloads; no model is downloaded automatically.
  Downloads verify the declared byte count and SHA-256 before installation.
- The frontend includes chat/history, search, Markdown/code rendering, model
  management, settings, local preferences storage, sharing, and haptics.

### Build and verification

From `mobile/`:

```sh
npm ci
npm run ios:build:sim
```

`ios:build:sim` builds the web bundle, builds/caches llama.cpp for Apple
platforms, syncs Capacitor, and builds the iPhone 17 simulator app without code
signing. The simulator app was installed and launched; its screen showed
successful llama.cpp/Metal runtime initialization. This confirms bridge startup,
not model inference or Metal generation performance.

The simulator smoke-test source is present, but the generated project does not
currently provide an Xcode test action for that package test target. Running
`swift test` on macOS is not applicable because the checked-in XCFramework has
only iOS device and simulator slices. A development fixture was not bundled or
added to the catalog. No model load, generation, cancellation, unload, or
whole-process memory measurement has been reported as successful.

The Android Studio/Gradle project and CPU JNI source are present, with Vulkan
opt-in but unverified. Android SDK, Java, Gradle, ADB, and Android Studio are
not installed in the current environment, so no Android compilation or APK
output is claimed. No IPA was signed or exported; no signing credentials were
used.

### Not implemented or not verified

- GGUF model loading, chat generation, cancellation, unload, model switching,
  low-memory behavior, and measured model compatibility.
- Android compilation/runtime and Vulkan acceleration.
- Physical iPhone/iPad/Android device testing, iPad orientation/Stage Manager,
  and Android phone/tablet testing.
- The iPhone 17 simulator screenshot shows a white region below the bottom
  navigation; the safe-area/window-background boundary still needs correction.
- Resumable/background model downloads, encrypted conversation storage,
  online research agents, voice, file/image attachments, and image analysis.
- A production release IPA/APK, app-store signing, and mobile release claims.

Conversation preferences are local to the app but are not encrypted. Online
research, voice, and attachment controls are not represented as working
features. Mobile builds and benchmarks must be treated separately from the
desktop release.

## Phase 1: Existing project compatibility

### Reusable

- The root `index.html` contains the branded chat interface, Markdown/code
  rendering, incremental response rendering, chat search, editing and
  regeneration controls, model/settings controls, and responsive phone-sized
  breakpoints. It is a single HTML/CSS/JavaScript application rather than a
  framework-specific renderer.
- The UI already uses a JSON/SSE HTTP contract for model listing and selection,
  chat generation, research streaming, image analysis, and speech
  transcription. This is a useful behavioral contract, but mobile cannot use
  the desktop backend process that currently serves it.
- Conversations use a simple local schema of chat IDs, titles, timestamps,
  user/assistant roles, and message text. Chat search and settings are already
  implemented in the UI.
- The app has an explicit generation abort path, streaming deltas, model
  selection, and research modes. These interactions can be preserved behind a
  platform adapter.
- Windows research already separates online search/source retrieval from
  local answer generation. It can inform a mobile research flow, but its
  Python agent module is not itself a mobile runtime.

### Not directly portable

- `main.js` is an Electron main process. It spawns Python, owns the loopback
  server lifecycle, stores application data, performs desktop OAuth, exposes
  filesystem-based CoCode operations, and uses macOS `say` for speech. None of
  these entry points should be reused as iOS or Android launchers.
- `preload.js` exposes the `window.electronAPI` bridge. Mobile needs a separate
  native bridge; desktop IPC and mobile plugin APIs must not be conflated.
- The frontend currently targets `http://127.0.0.1:8741`. That address is
  available only because Electron starts the local Python server. A mobile
  build must call native inference and storage APIs, not assume a server is
  listening.
- The macOS backend imports Python MLX and MLX-LM and loads MLX model
  repositories. That Python environment and model format do not run unchanged
  on iOS or Android. The Ollama coding-model integration is also desktop-only.
- The Windows backend uses `llama-cpp-python` and GGUF files, but pins inference
  to CPU (`n_gpu_layers=0`) and is still a desktop Python service. Its
  first-launch behavior downloads all five Windows models; that is unsuitable
  for mobile storage and memory budgets.
- The desktop research specialists use MLX on macOS. Mobile research must not
  assume those specialist models or Python agents are present. Web search and
  source retrieval require network access; they must be visibly distinguished
  from on-device generation and disabled when offline.
- The existing chat UI keeps conversation text in local browser storage when
  Electron persistence is unavailable. Desktop Electron state is a local JSON
  file. Neither mechanism provides the explicit encrypted mobile database and
  platform-key handling required for the mobile privacy target.
- The current phone breakpoint turns the desktop sidebar into a drawer; there
  is no dedicated iPad/tablet navigation layout or native keyboard, lifecycle,
  download, low-memory, or safe-area integration.
- Image analysis and speech transcription use MLX-specific Python modules on
  macOS; Windows returns unsupported responses for those operations. They
  need native implementations or must be explicitly unavailable in a mobile
  release. Text-to-speech also currently has platform-specific fallbacks.

## Phase 2: Selected mobile architecture

### Capacitor shell with native on-device inference

Use an isolated `mobile/` Capacitor application that packages a shared,
mobile-first web UI and native iOS and Android projects. Capacitor is a better
fit than Electron for reusing the existing HTML/CSS/JavaScript interface while
still producing real platform applications and native plugin entry points.
The WebView is only the presentation layer; it is not the inference engine.

Add a typed mobile platform adapter for chat streaming, model management,
conversation storage, file/photo selection, audio, haptics, and sharing. The
desktop adapter continues to use the current Electron bridge and desktop HTTP
backend. Do not change the desktop process model to accommodate mobile.

### Local inference and model format

Use a pinned `llama.cpp` native runtime and a curated GGUF model catalog as the
common initial inference path:

- iOS/iPadOS: native Swift/Objective-C++ bridge to the C/C++ runtime, using
  Metal where the device/runtime build supports it.
- Android: Kotlin/JNI bridge to the same runtime, using Vulkan only when the
  device/runtime build supports it and CPU otherwise. Report the selected
  backend accurately; never label CPU inference as GPU accelerated.
- Run one model at a time. Cancel generation, release the old context/model,
  and handle iOS memory warnings and Android trim-memory callbacks before
  activating another model.
- Do not reuse MLX Python packages on mobile. Core ML would require a distinct
  model-conversion/runtime path and model-specific validation; it is not the
  first shared iOS/Android backend.

The existing MLX model repositories are not automatically compatible with this
GGUF runtime. Mobile needs its own catalog with verified model files, exact
byte sizes, licenses, checksums, context limits, and conservative minimum RAM
and free-storage requirements. Recommend a small model based on native
hardware/storage data; download only after user selection. Support resumable
downloads, integrity checks, cancellation, deletion, and installation/loading
progress.

### Persistence, research, and native features

- Store chat history and preferences in a mobile-local database, encrypted
  using a key protected by Keychain on Apple platforms and Android Keystore on
  Android. Keep model files separate from encrypted conversation data.
- Make online research opt-in on mobile. Clearly label that search sends a
  search query to the network and that no web research is available offline.
  Keep model inference on-device and do not send private conversation history
  unless the user explicitly initiates a research action.
- Implement phone navigation and keyboard/safe-area behavior separately from
  the tablet layout. Use a tablet sidebar/navigation rail and adaptive
  multi-column layout rather than scaling the desktop view.
- Use native plugins for background/resumable downloads, device storage and
  memory signals, photo/file picking, speech recognition/synthesis, clipboard,
  haptics, and the system share sheet. Each feature must be wired and tested or
  shown as unavailable; no placeholder controls.
- Preserve the desktop API and `main.js`/`preload.js` entry points. Mobile
  builds must not package or launch the desktop Python servers.

### Build and verification requirements

- iOS/iPadOS: generate and maintain an Xcode project with one universal iPhone
  and iPad target. Simulator builds do not prove physical-device inference.
  An installable signed IPA requires an Apple distribution certificate and
  provisioning profile; do not claim or create a signed IPA without them.
- Android: generate an Android Studio/Gradle project and a single responsive
  APK with ARM64 plus other practical ABIs. A release APK requires a configured
  signing key; never put key material in source control.
- Test actual chat generation, cancellation, switching, interrupted/resumed
  model downloads, persistence, research online/offline states, and UI
  orientations on simulators/emulators and then on real devices. Record device,
  OS, runtime backend, and whole-app memory measurements. Desktop benchmarks
  are not mobile performance claims.

## Build environment observed

- Host: Apple Silicon macOS.
- Xcode and iOS/iOS Simulator SDKs are installed; iOS 26.5 and 27.0 simulator
  runtimes are available. The iPhone 17 simulator app builds and launches.
- Android prerequisites are absent: no Android SDK/`sdkmanager`, Gradle, ADB,
  Android Studio installation, or Java runtime was found. Consequently an
  Android APK cannot be built or tested in the current environment without
  installing/configuring that toolchain.
- No IPA/APK or signing configuration is present in the repository. No
  physical-device tests have been run.
