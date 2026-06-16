"""Silero VAD — voice activity detection."""

import numpy as np


class VAD:
    def __init__(self, threshold: float = 0.5):
        self._threshold = threshold
        self._model = None
        self._sample_rate = 16000
        self._loaded = False

    def load(self):
        try:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
            )
            self._model = model
            (self._get_speech_timestamps,
             self._save_audio,
             self._read_audio,
             self._vad_iterator,
             self._collect_chunks) = utils
            self._loaded = True
            return True
        except Exception as e:
            print(f"VAD load failed: {e}")
            return False

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        if not self._loaded:
            return False
        try:
            import torch
            tensor = torch.from_numpy(audio_chunk).float()
            prob = self._model(tensor, self._sample_rate).item()
            return prob >= self._threshold
        except Exception:
            return False

    def is_loaded(self) -> bool:
        return self._loaded
