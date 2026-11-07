"""Regression tests for the MLX chat prompt and cache configuration."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import server


class ChatGenerationRegressionTests(unittest.TestCase):
    def test_llama32_uses_uncensored_six_bit_repository(self):
        self.assertEqual(
            "mlx-community/Llama-3.2-3B-Instruct-uncensored-6bit",
            server.MODELS["llama32"]["repo"],
        )

    def test_adjacent_same_role_messages_are_merged(self):
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "First failed request"},
            {"role": "user", "content": "Second request"},
            {"role": "assistant", "content": "Reply"},
            {"role": "assistant", "content": "Continuation"},
        ]

        self.assertEqual(
            [
                {"role": "system", "content": "System prompt"},
                {
                    "role": "user",
                    "content": "First failed request\n\nSecond request",
                },
                {"role": "assistant", "content": "Reply\n\nContinuation"},
            ],
            server.coalesce_messages(messages),
        )
        self.assertEqual("First failed request", messages[1]["content"])

    def test_gemma2_uses_an_unquantized_kv_cache(self):
        self.assertIsNone(server.kv_bits_for_model("gemma2"))

    def test_other_models_keep_the_configured_kv_cache(self):
        self.assertEqual(server.KV_BITS, server.kv_bits_for_model("llama32"))

    def test_coding_model_uses_the_requested_ollama_gguf(self):
        model = server.MODELS["stablecode"]
        self.assertEqual(
            "mradermacher/DeepSeek-R1-Distill-Qwen-1.5B-abliterated-GGUF:Q4_K_M",
            model["repo"],
        )
        self.assertEqual("ollama", model["provider"])
        self.assertIn("Q4_K_M.gguf", model["gguf_url"])
        self.assertIn("huggingface.co/mradermacher/", model["gguf_url"])

    def test_ollama_payload_preserves_chat_messages_and_generation_settings(self):
        request = server.ChatRequest(
            messages=[
                server.Message(role="system", content="Write code."),
                server.Message(role="user", content="Print hello."),
            ],
            max_tokens=256,
            temperature=0.2,
            top_p=0.8,
        )

        payload = server.ollama_chat_payload(request)

        self.assertEqual(
            server.MODELS["stablecode"]["ollama_model"], payload["model"]
        )
        self.assertEqual(
            [
                {"role": "system", "content": "Write code."},
                {"role": "user", "content": "Print hello."},
            ],
            payload["messages"],
        )
        self.assertEqual(
            {"num_predict": 256, "temperature": 0.2, "top_p": 0.8},
            payload["options"],
        )

    def test_ollama_stream_is_translated_to_chat_deltas_and_stats(self):
        response = io.BytesIO(
            b'{"message":{"content":"print("},"done":false}\n'
            b'{"message":{"content":"hello)"},"done":false}\n'
            b'{"done":true,"eval_count":2,"prompt_eval_count":5,"total_duration":1000000000}\n'
        )
        request = server.ChatRequest(
            messages=[server.Message(role="user", content="Print hello.")]
        )

        with patch("server.urllib.request.urlopen", return_value=response) as urlopen:
            events = list(server.ollama_chat_events(request))

        self.assertEqual(
            [{"delta": "print("}, {"delta": "hello)"}, {
                "done": {
                    "done": True,
                    "eval_count": 2,
                    "prompt_eval_count": 5,
                    "total_duration": 1_000_000_000,
                },
            }],
            events,
        )
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(
            server.MODELS["stablecode"]["ollama_model"], sent["model"]
        )

    def test_ollama_import_uses_a_local_gguf_modelfile(self):
        config = server.MODELS["stablecode"]
        command = server.ollama_create_command(
            "/usr/local/bin/ollama",
            config["ollama_model"],
            server.Path("/tmp/Modelfile"),
        )

        self.assertEqual(
            [
                "/usr/local/bin/ollama",
                "create",
                config["ollama_model"],
                "-f",
                "/tmp/Modelfile",
            ],
            command,
        )

    def test_public_gguf_download_is_cached_and_validated(self):
        response = io.BytesIO(b"GGUFmodel")
        response.status = 200
        response.headers = {"Content-Length": "9"}

        with tempfile.TemporaryDirectory() as support_dir, \
             patch.dict(os.environ, {"SXARF_SUPPORT_DIR": support_dir}), \
             patch("server.urllib.request.urlopen", return_value=response):
            model_config = {
                **server.MODELS["stablecode"],
                "gguf_size": 9,
            }
            model_path = server.download_ollama_gguf(model_config)
            self.assertEqual(b"GGUFmodel", model_path.read_bytes())
            self.assertEqual(
                "DeepSeek-R1-Distill-Qwen-1.5B-abliterated.Q4_K_M.gguf",
                model_path.name,
            )


if __name__ == "__main__":
    unittest.main()
