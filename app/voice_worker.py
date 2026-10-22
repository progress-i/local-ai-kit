"""Short-lived Piper process; the ONNX model is released when it exits."""
import argparse
from pathlib import Path
import sys
import wave

from piper import PiperVoice

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
text = sys.stdin.buffer.read(16001).decode("utf-8")
if not text.strip() or len(text) > 1600:
    raise SystemExit("Ожидался текст длиной 1–1600 символов.")
voice = PiperVoice.load(str(Path(args.model)), use_cuda=False)
with wave.open(str(args.output), "wb") as wav:
    voice.synthesize_wav(text, wav)
