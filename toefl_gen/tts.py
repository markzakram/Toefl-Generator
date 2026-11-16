"""Pembuatan audio Listening dengan text-to-speech.

Naskah memakai peran suara (male1, female2, ...), bukan nama suara, supaya mesin TTS
bisa diganti tanpa mengubah rencana. Setiap mesin memetakan peran ke suaranya sendiri.
"""

import asyncio
import hashlib
import json
from pathlib import Path

import aiohttp
import edge_tts

# Frame MP3 hening untuk keluaran edge-tts (MPEG-2 Layer III, 24 kHz, 48 kbps, mono): 144 byte = 24 ms.
SILENT_FRAME = bytes([0xFF, 0xF3, 0x64, 0xC4]) + bytes(140)
FRAME_MS = 24
PAUSE_LINE_MS = 600
PAUSE_NARRATOR_MS = 1000


class TTSError(Exception):
    pass


def silence(ms):
    return SILENT_FRAME * round(ms / FRAME_MS)


class EdgeTTS:
    name = "edge-tts"
    bytes_per_second = 6000
    timeout = 60
    VOICES = {
        "male1": "en-US-AndrewMultilingualNeural",
        "male2": "en-US-BrianMultilingualNeural",
        "female1": "en-US-AvaMultilingualNeural",
        "female2": "en-US-EmmaMultilingualNeural",
        "narrator": "en-US-ChristopherNeural",
    }

    async def _stream(self, text, voice):
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return bytes(audio)

    async def speak(self, text, voice, tries=6):
        # Layanan edge-tts kadang tidak mengirim audio, macet, atau menolak sementara saat permintaan
        # banyak; coba ulang dengan jeda yang makin panjang (total sekitar 2 menit).
        for attempt in range(1, tries + 1):
            try:
                return await asyncio.wait_for(self._stream(text, voice), self.timeout)
            except (edge_tts.exceptions.NoAudioReceived, asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt == tries:
                    raise TTSError(f"edge-tts gagal untuk suara {voice}: {type(e).__name__}") from e
                await asyncio.sleep(min(60, 2 ** (attempt + 1)))

    async def render(self, script, roles):
        out = bytearray()
        for speaker, text in script:
            voice = self.VOICES["narrator" if speaker == "NARRATOR" else roles[speaker]]
            out += await self.speak(text, voice)
            out += silence(PAUSE_NARRATOR_MS if speaker == "NARRATOR" else PAUSE_LINE_MS)
        return bytes(out)


def render_items(items, audio_dir, engine, log=print, concurrency=3):
    """Buat file audio untuk setiap Item Listening. Kembalikan jumlah file yang dibuat."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audio_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    jobs = []
    for it in items:
        key = hashlib.sha256(json.dumps([engine.name, it.meta["audio_script"], it.meta["voices"]],
                                        sort_keys=True).encode("utf-8")).hexdigest()[:16]
        path = audio_dir / it.meta["audio_file"]
        it.meta["audio_path"] = str(path)
        if manifest.get(it.meta["audio_file"]) == key and path.exists() and path.stat().st_size:
            continue
        jobs.append((it, path, key))

    async def run():
        sem = asyncio.Semaphore(concurrency)

        async def one(it, path, key):
            async with sem:
                path.write_bytes(await engine.render(it.meta["audio_script"], it.meta["voices"]))
                manifest[it.meta["audio_file"]] = key
                # Disimpan per file supaya proses yang terhenti bisa dilanjutkan tanpa mengulang.
                manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
                log(f"  audio {it.meta['audio_file']}")

        await asyncio.gather(*(one(*job) for job in jobs))

    if jobs:
        asyncio.run(run())
    for it in items:
        it.meta["audio_seconds"] = round(Path(it.meta["audio_path"]).stat().st_size / engine.bytes_per_second, 1)
    return len(jobs)
