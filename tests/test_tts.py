import asyncio

import pytest

from toefl_gen import tts


class StubCommunicate:
    """Panggilan pertama macet tanpa batas; panggilan berikutnya mengirim audio."""

    calls = 0

    def __init__(self, text, voice):
        pass

    async def stream(self):
        type(self).calls += 1
        if type(self).calls == 1:
            await asyncio.sleep(3600)
        yield {"type": "audio", "data": b"mp3"}


class AlwaysStuck:
    def __init__(self, text, voice):
        pass

    async def stream(self):
        await asyncio.sleep(3600)
        yield {"type": "audio", "data": b""}


def fast_engine():
    engine = tts.EdgeTTS()
    engine.timeout = 0.05
    return engine


def test_speak_retries_after_hang(monkeypatch):
    StubCommunicate.calls = 0
    monkeypatch.setattr(tts.edge_tts, "Communicate", StubCommunicate)
    assert asyncio.run(fast_engine().speak("hello", "voice")) == b"mp3"
    assert StubCommunicate.calls == 2


def test_speak_gives_up_with_clear_error(monkeypatch):
    monkeypatch.setattr(tts.edge_tts, "Communicate", AlwaysStuck)
    with pytest.raises(tts.TTSError):
        asyncio.run(fast_engine().speak("hello", "voice", tries=2))
