"""Silent, dependency-free backend for the explicitly selected --ui-only mode."""

import wave
from types import SimpleNamespace


class DemoTokenizer:
    def encode(self, text, **kwargs):
        return list(text)

    def tokenize(self, text):
        return list(text)

    def split_segments(self, tokens, max_text_tokens_per_segment=120):
        size = int(max_text_tokens_per_segment)
        return [tokens[i:i + size] for i in range(0, len(tokens), size)]


class DemoTTS:
    def __init__(self, version):
        self.model_version = f"{version} UI DEMO"
        self.cfg = SimpleNamespace(gpt=SimpleNamespace(max_mel_tokens=2000, max_text_tokens=200))
        self.tokenizer = DemoTokenizer()
        self.gr_progress = None

    def split_text_by_tokens(self, text, size, lang_prefix):
        return [text[i:i + size] for i in range(0, len(text), size)]

    def normalize_emo_vec(self, vector, apply_bias=True):
        return vector

    def infer(self, *, spk_audio_prompt, text, output_path, **kwargs):
        # This is a UI fixture, never a speech synthesizer.
        with wave.open(str(output_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22050)
            audio.writeframes(b"\x00\x00" * 11025)
        return output_path
