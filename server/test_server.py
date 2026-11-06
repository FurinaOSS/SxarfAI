"""Regression tests for the MLX chat prompt and cache configuration."""
import unittest

import server


class ChatGenerationRegressionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
