import asyncio
import io
import math
import struct
import subprocess
import wave

import imageio_ffmpeg
import pytest

from echo.audio_codec import AudioCodecError, normalize_audio


def wav_fixture(seconds=0.1):
    frames = b"".join(struct.pack("<h", int(1000*math.sin(i*2*math.pi*440/16000))) for i in range(int(seconds*16000)))
    output=io.BytesIO()
    with wave.open(output,"wb") as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000);writer.writeframes(frames)
    return output.getvalue()


@pytest.mark.asyncio
async def test_real_local_ogg_opus_normalizes_to_supported_mono_wav():
    # A generated tone exercises decoding only; it is not a speech-quality test.
    encoded=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-nostdin","-v","error","-protocol_whitelist","pipe","-i","pipe:0","-c:a","libopus","-f","ogg","pipe:1"],input=wav_fixture(),capture_output=True,check=True).stdout
    assert encoded.startswith(b"OggS")
    decoded=await normalize_audio(encoded)
    assert decoded.startswith(b"RIFF")
    with wave.open(io.BytesIO(decoded),"rb") as reader:
        assert (reader.getnchannels(),reader.getsampwidth(),reader.getframerate())==(1,2,16000)
        assert 0<reader.getnframes()<=2000


@pytest.mark.asyncio
async def test_corrupt_audio_has_sanitized_decoder_error():
    with pytest.raises(AudioCodecError) as caught:
        await normalize_audio(b"not audio with private details")
    assert caught.value.code=="invalid_audio"
    assert "private" not in str(caught.value)


@pytest.mark.asyncio
async def test_more_than_five_minutes_is_rejected_instead_of_silently_truncated():
    output=io.BytesIO()
    with wave.open(output,"wb") as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000);writer.writeframes(b"\0"*(301*16000*2))
    with pytest.raises(AudioCodecError) as caught:
        await normalize_audio(output.getvalue())
    assert caught.value.code=="audio_too_long"


@pytest.mark.asyncio
async def test_stuck_decoder_is_killed_and_timeout_is_sanitized(monkeypatch):
    from echo import audio_codec
    class Input:
        def write(self,data):pass
        async def drain(self):pass
        def close(self):pass
        async def wait_closed(self):pass
    class Output:
        async def read(self,count):
            await asyncio.sleep(60)
    class Process:
        stdin=Input();stdout=Output();returncode=None;killed=False
        def kill(self):self.killed=True;self.returncode=-9
        async def wait(self):return self.returncode
    process=Process()
    async def spawn(*args,**kwargs):
        assert "-protocol_whitelist" in args and args[args.index("-protocol_whitelist")+1]=="pipe"
        assert kwargs.get("shell") in {None,False}
        return process
    monkeypatch.setattr(audio_codec.asyncio,"create_subprocess_exec",spawn)
    monkeypatch.setattr(audio_codec,"CODEC_TIMEOUT_SECONDS",0.01)
    with pytest.raises(AudioCodecError) as caught:
        await normalize_audio(wav_fixture())
    assert caught.value.code=="audio_decode_timeout" and process.killed
