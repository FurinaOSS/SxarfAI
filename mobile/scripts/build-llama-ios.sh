#!/bin/bash
set -euo pipefail

MOBILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="$MOBILE_DIR/native/llama.cpp"
BUILD_DIR="$LLAMA_DIR/build-apple"
FRAMEWORK="$BUILD_DIR/llama.xcframework"
STAMP="$BUILD_DIR/.sxarf-source-commit"
SOURCE_COMMIT="$(git -C "$LLAMA_DIR" rev-parse HEAD)"

if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$SOURCE_COMMIT" && -d "$FRAMEWORK" ]]; then
    echo "Using llama.cpp XCFramework for pinned commit $SOURCE_COMMIT"
    exit 0
fi

(
    cd "$LLAMA_DIR"
    ./build-xcframework.sh ios-sim ios-device
)

printf '%s\n' "$SOURCE_COMMIT" > "$STAMP"
echo "Built simulator and device llama.cpp slices for $SOURCE_COMMIT"
