#!/usr/bin/env python3
"""One-shot MLX-VLM worker. Exiting releases this process's model allocations."""

import argparse
import json
import os
import sys
from contextlib import redirect_stdout

MODEL_ID = "mlx-community/SmolVLM-500M-Instruct-4bit"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument(
        "--prompt",
        default="Describe the image accurately. Focus on visible details.",
    )
    args = parser.parse_args()

    try:
        # Keep stdout reserved for the JSON response. MLX progress output
        # is redirected to stderr so it cannot corrupt the response.
        with redirect_stdout(sys.stderr):
            import mlx.core as mx
            from mlx_vlm import load, generate
            from mlx_vlm.prompt_utils import apply_chat_template
            from mlx_vlm.utils import load_config

            memory_limit = int(max(0.5, min(float(os.getenv("MLX_MEMORY_LIMIT_GB", "2.5")),
                                            2.5)) * 1024**3)
            cache_limit = int(max(0.05, min(float(os.getenv("MLX_CACHE_LIMIT_GB", "0.25")),
                                            0.25)) * 1024**3)
            mx.set_memory_limit(memory_limit)
            mx.set_cache_limit(cache_limit)
            model, processor = load(MODEL_ID)
            config = load_config(MODEL_ID)

            results = []
            for image_path in args.image:
                formatted_prompt = apply_chat_template(
                    processor,
                    config,
                    args.prompt,
                    num_images=1,
                )
                output = generate(
                    model,
                    processor,
                    formatted_prompt,
                    [image_path],
                    max_tokens=256,
                    temp=0.0,
                )

                description = getattr(output, "text", None)
                if description is None:
                    description = str(output)

                results.append({
                    "description": str(description).strip()
                })

        sys.stdout.write(json.dumps(
            {"results": results},
            ensure_ascii=False,
        ))
        sys.stdout.flush()

    except Exception as exc:
        print(
            f"[Vision worker] {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
