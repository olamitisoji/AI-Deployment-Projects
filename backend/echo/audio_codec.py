"""Bounded, pipe-only local decoding into documented transcription input WAV."""
import asyncio
import io
import wave

import imageio_ffmpeg


CODEC_TIMEOUT_SECONDS = 30
MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_PCM_BYTES = 300 * 16000 * 2


class AudioCodecError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


async def normalize_audio(audio: bytes) -> bytes:
    """Decode at most five minutes to mono 16kHz PCM WAV, retaining no files.

    ffmpeg gets only stdin/stdout pipes; file, HTTP and other input protocols are
    disabled. Its diagnostics are discarded so participant data is never logged.
    """
    if not audio or len(audio) > MAX_INPUT_BYTES:
        raise AudioCodecError("invalid_audio")
    process = writer = None

    async def decode():
        nonlocal process, writer
        try:
            executable = imageio_ffmpeg.get_ffmpeg_exe()
            process = await asyncio.create_subprocess_exec(
                executable, "-nostdin", "-v", "error", "-threads", "1",
                "-protocol_whitelist", "pipe", "-i", "pipe:0",
                "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", "301",
                "-threads", "1", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, RuntimeError):
            raise AudioCodecError("audio_decoder_unavailable") from None

        async def feed():
            try:
                # Concurrent stdin/output handling avoids a full pipe deadlock.
                process.stdin.write(audio)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        writer = asyncio.create_task(feed())
        pcm = bytearray()
        while chunk := await process.stdout.read(64 * 1024):
            if len(pcm) + len(chunk) > MAX_PCM_BYTES:
                raise AudioCodecError("audio_too_long")
            pcm.extend(chunk)
        await writer
        result = await process.wait()
        if result != 0 or not pcm or len(pcm) % 2:
            raise AudioCodecError("invalid_audio")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        return output.getvalue()

    try:
        return await asyncio.wait_for(decode(), timeout=CODEC_TIMEOUT_SECONDS)
    except TimeoutError:
        raise AudioCodecError("audio_decode_timeout") from None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        if writer is not None:
            if not writer.done():
                writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
