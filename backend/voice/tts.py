"""Coqui TTS — streaming text-to-speech with interrupt support."""

import threading
import time


class TTS:
    def __init__(self, speed: float = 1.0):
        self._speed = speed
        self._model = None
        self._loaded = False
        self._playing = False
        self._interrupted = False
        self._thread: threading.Thread | None = None

    def load(self):
        try:
            from TTS.api import TTS as CoquiTTS
            self._model = CoquiTTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False)
            self._loaded = True
            return True
        except Exception as e:
            print(f"TTS load failed: {e}")
            return False

    def speak(self, text: str):
        if not self._loaded:
            return
        self._interrupted = False
        self._thread = threading.Thread(target=self._speak_thread, args=(text,), daemon=True)
        self._thread.start()

    def _speak_thread(self, text: str):
        self._playing = True
        try:
            import sounddevice as sd
            import numpy as np
            audio = self._model.tts(text)
            audio_np = np.array(audio, dtype=np.float32)
            sd.play(audio_np, samplerate=22050)
            while sd.get_stream().active:
                if self._interrupted:
                    sd.stop()
                    break
                time.sleep(0.05)
        except Exception as e:
            print(f"TTS playback error: {e}")
        finally:
            self._playing = False

    def stop(self):
        self._interrupted = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def is_speaking(self) -> bool:
        return self._playing

    def is_loaded(self) -> bool:
        return self._loaded
