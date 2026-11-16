"""Pemanggil Claude API untuk keluaran JSON terstruktur."""

import json
import threading
from collections import Counter

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"

# Harga per 1 juta token (USD): input, output, baca cache. Sumber: tabel model Claude API (Oktober 2026).
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
}


class LLMError(Exception):
    pass


class ClaudeClient:
    def __init__(self, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT):
        try:
            self.client = anthropic.Anthropic()
        except anthropic.AnthropicError as e:
            raise LLMError("Kredensial Claude API belum ada. Isi ANTHROPIC_API_KEY di file .env.") from e
        self.model = model
        self.effort = effort
        self.usage = Counter()
        self._lock = threading.Lock()

    def generate_json(self, system, prompt, schema, max_tokens=32000, effort=None):
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": effort or self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMError("API key ditolak. Periksa ANTHROPIC_API_KEY di file .env.") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Permintaan ditolak API: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Batas pemakaian API tercapai. Coba lagi beberapa saat lagi.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Galat API ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Tidak bisa terhubung ke Claude API. Periksa koneksi internet.") from e
        except TypeError as e:
            # SDK baru memeriksa kredensial saat permintaan dikirim.
            if "authentication" in str(e):
                raise LLMError("Kredensial Claude API belum ada. Isi ANTHROPIC_API_KEY di file .env.") from e
            raise

        usage = message.usage
        with self._lock:
            self.usage["input"] += usage.input_tokens
            self.usage["output"] += usage.output_tokens
            self.usage["cache_read"] += usage.cache_read_input_tokens or 0
            self.usage["cache_write"] += usage.cache_creation_input_tokens or 0
            self.usage["calls"] += 1

        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            raise LLMError(f"Model menolak permintaan (kategori: {category}).")
        if message.stop_reason == "max_tokens":
            raise LLMError("Jawaban model terpotong karena batas max_tokens.")
        text = next((b.text for b in message.content if b.type == "text"), None)
        if text is None:
            raise LLMError("Model tidak mengembalikan teks.")
        return json.loads(text)

    def cost_usd(self):
        price_in, price_out, price_cache = PRICES.get(self.model, PRICES[DEFAULT_MODEL])
        u = self.usage
        # Penulisan cache ditagih 1,25x harga input.
        return (u["input"] * price_in + u["cache_write"] * price_in * 1.25
                + u["cache_read"] * price_cache + u["output"] * price_out) / 1_000_000
