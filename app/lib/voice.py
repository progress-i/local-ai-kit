"""Local WAV-only voice path: Whisper CPU -> LLM -> Piper CPU."""
import base64
import io
from pathlib import Path
import subprocess
import tempfile
import wave

from .common import APP, env_python, execute, project_env


def validate_wav(data):
    if len(data) > 1_000_000:
        raise ValueError("Запись длиннее 30 секунд.")
    with wave.open(io.BytesIO(data), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Требуется WAV PCM 16-bit, 16 kHz, mono.")
        if not 1600 <= w.getnframes() <= 480000:
            raise ValueError("Длина записи: от 0.1 до 30 секунд.")
        frames = w.readframes(w.getnframes())
        if len(frames) != w.getnframes() * 2:
            raise ValueError("WAV обрезан.")


def transcribe(root: Path, data: bytes):
    from manage import whisper_binary
    validate_wav(data)
    with tempfile.TemporaryDirectory(dir=root / "tmp", prefix="stt-") as directory:
        path = Path(directory) / "input.wav"
        output = Path(directory) / "transcript"
        path.write_bytes(data)
        execute([whisper_binary(root), "--model", root / "models/ggml-base.bin", "--file", path,
                 "--language", "ru", "--threads", "4", "--no-gpu", "--output-txt", "--output-file", output],
                root, capture=True, timeout=180)
        text = output.with_suffix(".txt").read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("Речь не распознана. Запишите фразу ещё раз.")
        return text


def synthesize(root: Path, text: str):
    if not isinstance(text, str) or not text.strip() or len(text) > 1600:
        raise ValueError("Озвучка принимает от 1 до 1600 символов.")
    with tempfile.TemporaryDirectory(dir=root / "tmp", prefix="tts-") as directory:
        output = Path(directory) / "speech.wav"
        command = [str(env_python(root)), "-B", str(APP / "voice_worker.py"), "--model",
                   str(root / "models/ru_RU-denis-medium.onnx"), "--output", str(output)]
        p = subprocess.run(command, input=text.encode("utf-8"), capture_output=True,
                           env=project_env(root), timeout=180)
        if p.returncode:
            raise RuntimeError("Piper: " + p.stderr.decode("utf-8", errors="replace")[-4000:])
        data = output.read_bytes()
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getnframes() == 0 or w.getsampwidth() != 2:
                raise RuntimeError("Piper вернул пустой WAV.")
        return data
