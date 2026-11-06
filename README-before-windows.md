# Sxarf AI

Sxarf AI is a desktop AI assistant for Apple Silicon Macs. It runs language
models on your Mac using MLX and combines chat with optional research, coding,
image, voice, and memory features.

## Download

**Version 2.0.0 · macOS · Apple Silicon (arm64)**

[Download the Sxarf AI 2.0.0 installer](./Sxarf%20AI-2.0.0-arm64.dmg)

This repository contains the installer. The app's first launch needs an
internet connection to set up its local runtime and download model files.

## Install

1. Download and open the `.dmg` file.
2. Drag **Sxarf AI** into **Applications**.
3. Open Sxarf AI. On first launch, it prepares the local AI backend and
   downloads required components; this can take a while.
4. Start a chat and choose a model from the model menu.

Sxarf AI requires a Mac with Apple Silicon (M1 or later) and macOS. Initial
setup requires Python 3.10 or later and an internet connection. Speech
transcription also requires `ffmpeg`. Keep enough free disk space for the
runtime and downloaded models.

## What it can do

- **Chat locally:** choose among supported MLX models, including SmolLM2,
  SmolLM3, Llama 3.2, Gemma 2, Phi 3.5, LFM2.5, and Stable Code.
- **Research:** use specialist agents to search the web and organize findings.
  Agent mode can be set to Auto, Always, or Off. Search availability depends
  on the search providers.
- **CoCode:** connect a project folder to work with its files from the
  assistant.
- **Image questions:** attach images for visual analysis.
- **Voice:** transcribe speech locally and use your Mac's built-in speech
  output.
- **Local context:** keep chat history, preferences, and long-term memory on
  this device.

Model quality, speed, and memory use vary by model and Mac. MLX allocation
limits do not guarantee a particular total system-memory footprint.

## Privacy and online services

Chat inference and image analysis run on your Mac. Sxarf AI may still use the
internet to download the runtime and models, and its research feature contacts
web search providers and public websites. Avoid sending sensitive information
to online services unless you are comfortable with their policies.

Google sign-in is optional and requires a configured Google Desktop OAuth
client. The app can be used without signing in. Paid plan names shown in the
interface are not active subscriptions; billing and paid access are not
implemented.

## Troubleshooting

- **Setup seems slow:** initial setup downloads Python packages and model
  files. Keep the app open and check your internet connection.
- **Backend setup fails:** confirm you are on Apple Silicon and have Python
  3.10+ installed, then relaunch the app.
- **Speech transcription fails:** install `ffmpeg` and try again.
- **Research returns no results:** web search can be unavailable or rate
  limited; try again later or turn agent mode off for a regular local chat.

## Technical overview

The desktop interface is built with Electron. A local Python FastAPI service
uses Apple's MLX framework for model inference. Models are downloaded from
Hugging Face and cached on the Mac.
