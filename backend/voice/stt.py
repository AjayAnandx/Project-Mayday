"""faster-whisper — speech-to-text transcription."""


class STT:
    def __init__(self, model_size: str = "tiny"):
        self._model_size = model_size
        self._model = None
        self._loaded = False

    def load(self):
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
            self._loaded = True
            return True
        except Exception as e:
            print(f"STT load failed: {e}")
            return False

    def transcribe(self, audio_path: str) -> str:
        if not self._loaded:
            return ""
        try:
            segments, _ = self._model.transcribe(audio_path, beam_size=1)
            return " ".join(seg.text for seg in segments)
        except Exception as e:
            return f"[transcription error: {e}]"

    def transcribe_array(self, audio: bytes, sample_rate: int = 16000) -> str:
        if not self._loaded:
            return ""
        try:
            import numpy as np
            audio_np = np.frombuffer(audio, dtype=np.float32).astype(np.float32)
            segments, _ = self._model.transcribe(audio_np, beam_size=1)
            return " ".join(seg.text for seg in segments)
        except Exception as e:
            return f"[transcription error: {e}]"

    def is_loaded(self) -> bool:
        return self._loaded
