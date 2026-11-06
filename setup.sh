#!/usr/bin/env bash
# One-time setup for Sxarf AI on Apple Silicon.
set -e
cd "$(dirname "$0")"
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
npm install

# Main + specialist models (cached by Hugging Face, downloaded once)
for repo in \
  mlx-community/Qwen3-4B-4bit \
  mlx-community/SmolLM2-360M-Instruct-6bit \
  mlx-community/Qwen3-Reranker-0.6B-mxfp8 \
  mlx-community/Qwen3-Embedding-0.6B-8bit ; do
  venv/bin/huggingface-cli download "$repo"
done
# Optional / experimental (may not be MLX-compatible):
#   venv/bin/huggingface-cli download Beebey/smallcoder-303m
echo "Done. Start with: npm start"
