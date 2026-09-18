import threading
import logging
from typing import Optional, List, Callable
import discord

logger = logging.getLogger('sargam.mixer')

# Check audioop availability (built-in up to Python 3.12, audioop-lts in 3.13+)
try:
    import audioop
except ImportError:
    audioop = None

# Fallback PCM operations in case audioop is unavailable
def _pcm_mul_fallback(data: bytes, factor: float) -> bytes:
    import array
    samples = array.array('h', data)
    for i in range(len(samples)):
        val = int(samples[i] * factor)
        samples[i] = max(-32768, min(32767, val))
    return samples.tobytes()

def _pcm_add_fallback(data1: bytes, data2: bytes) -> bytes:
    import array
    s1 = array.array('h', data1)
    s2 = array.array('h', data2)
    length = min(len(s1), len(s2))
    res = array.array('h', [0] * length)
    for i in range(length):
        val = s1[i] + s2[i]
        res[i] = max(-32768, min(32767, val))
    return res.tobytes()

def pcm_mul(data: bytes, factor: float) -> bytes:
    """Scales 16-bit PCM stereo audio by a volume factor with clipping."""
    if not data or factor == 1.0:
        return data
    if factor <= 0.0:
        return b'\x00' * len(data)
    if audioop is not None:
        try:
            return audioop.mul(data, 2, min(factor, 2.0))
        except Exception:
            pass
    return _pcm_mul_fallback(data, factor)

def pcm_add(data1: bytes, data2: bytes) -> bytes:
    """Mixes two 16-bit PCM byte sequences together with saturation clipping."""
    if not data1:
        return data2
    if not data2:
        return data1
    if audioop is not None:
        try:
            return audioop.add(data1, data2, 2)
        except Exception:
            pass
    return _pcm_add_fallback(data1, data2)


class OverlaySound:
    """Encapsulates a sound effect overlay, its volume, and its source."""
    def __init__(self, source: discord.AudioSource, volume: float = 1.0, duck_music: bool = True):
        self.source = source
        self.volume = max(0.0, min(volume, 2.0))
        self.duck_music = duck_music
        self.finished = False

    def read(self) -> bytes:
        try:
            return self.source.read()
        except Exception as e:
            logger.error(f"Error reading overlay sound: {e}")
            return b''

    def cleanup(self):
        try:
            self.source.cleanup()
        except Exception as e:
            logger.debug(f"Error cleaning up overlay sound: {e}")


class AudioMixer(discord.AudioSource):
    """
    Real-time composite AudioSource for discord.py.
    Plays a primary music stream while simultaneously mixing overlay sound effects
    (join sounds) with automatic audio ducking or pause-and-resume fallback.
    """
    FRAME_SIZE = 3840  # 20ms of 16-bit 48000Hz stereo PCM (48000 * 2 channels * 2 bytes * 0.02)

    def __init__(self):
        self._lock = threading.RLock()
        self.music_source: Optional[discord.AudioSource] = None
        self.music_volume: float = 0.5
        self.music_paused: bool = False
        self.duck_volume: float = 0.25  # Music ducks to 25% during join sound
        self.pause_resume_mode: bool = False  # If True, pause music instead of ducking
        self.overlays: List[OverlaySound] = []
        self.on_music_end: Optional[Callable] = None
        self._is_playing_mixer: bool = False
        self._empty_music_frames: int = 0

    def is_opus(self) -> bool:
        return False

    def has_music(self) -> bool:
        with self._lock:
            return self.music_source is not None

    def is_music_paused(self) -> bool:
        with self._lock:
            return self.music_paused

    def has_overlays(self) -> bool:
        with self._lock:
            return len(self.overlays) > 0

    def is_active(self) -> bool:
        """Returns True if either music or at least one overlay is currently playing."""
        with self._lock:
            return (self.music_source is not None and not self.music_paused) or len(self.overlays) > 0

    def set_music(self, source: discord.AudioSource, on_end: Optional[Callable] = None):
        """Set or replace the current primary music track."""
        with self._lock:
            if self.music_source:
                try:
                    self.music_source.cleanup()
                except Exception:
                    pass
            self.music_source = source
            self.on_music_end = on_end
            self.music_paused = False
            self._empty_music_frames = 0

    def stop_music(self):
        """Stops current music track and triggers on_end callback."""
        callback = None
        with self._lock:
            if self.music_source:
                try:
                    self.music_source.cleanup()
                except Exception:
                    pass
                self.music_source = None
            self.music_paused = False
            callback = self.on_music_end
            self.on_music_end = None

        if callback:
            try:
                callback(None)
            except Exception as e:
                logger.error(f"Error executing music end callback: {e}")

    def pause_music(self):
        """Pause only the music stream while allowing overlays to continue."""
        with self._lock:
            self.music_paused = True

    def resume_music(self):
        """Resume the paused music stream."""
        with self._lock:
            self.music_paused = False

    def add_overlay(self, source: discord.AudioSource, volume: float = 1.0, duck_music: bool = True) -> OverlaySound:
        """Add a sound effect overlay to be mixed simultaneously in real-time."""
        overlay = OverlaySound(source, volume=volume, duck_music=duck_music)
        with self._lock:
            self.overlays.append(overlay)
        return overlay

    def stop_all(self):
        """Stops music and all active overlays."""
        with self._lock:
            if self.music_source:
                try:
                    self.music_source.cleanup()
                except Exception:
                    pass
                self.music_source = None
            for ov in self.overlays:
                ov.cleanup()
            self.overlays.clear()
            self.on_music_end = None
            self.music_paused = False

    def read(self) -> bytes:
        """
        Invoked every 20ms by discord.py's AudioPlayer thread.
        Reads active overlays first to determine real-time ducking state,
        reads and mixes music PCM, and outputs a 3840-byte PCM frame.
        """
        music_callback = None
        mixed_buffer = b''

        with self._lock:
            # 1. Read and collect active overlays first
            remaining_overlays = []
            overlay_chunks = []
            ducking_active = False

            for ov in self.overlays:
                ov_data = ov.read()
                if ov_data:
                    # Pad to FRAME_SIZE if shorter
                    if len(ov_data) < self.FRAME_SIZE:
                        ov_data = ov_data + b'\x00' * (self.FRAME_SIZE - len(ov_data))
                    scaled_ov = pcm_mul(ov_data, ov.volume)
                    overlay_chunks.append(scaled_ov)
                    remaining_overlays.append(ov)
                    if ov.duck_music:
                        ducking_active = True
                else:
                    ov.cleanup()

            self.overlays = remaining_overlays
            has_overlays = len(overlay_chunks) > 0

            # Determine whether music should be paused or ducked
            duck_factor = 1.0
            if has_overlays:
                if self.pause_resume_mode:
                    # In pause-and-resume fallback mode, do not read music frame
                    duck_factor = 0.0
                elif ducking_active:
                    duck_factor = self.duck_volume

            # 2. Read music frame
            music_chunk = b''
            if self.music_source and not self.music_paused and duck_factor > 0.0:
                try:
                    raw_music = self.music_source.read()
                    if raw_music:
                        self._empty_music_frames = 0
                        effective_vol = self.music_volume * duck_factor
                        music_chunk = pcm_mul(raw_music, effective_vol)
                        if len(music_chunk) < self.FRAME_SIZE:
                            music_chunk = music_chunk + b'\x00' * (self.FRAME_SIZE - len(music_chunk))
                    else:
                        # Allow a grace period of 25 consecutive empty frames (~500ms) for stream buffering
                        self._empty_music_frames += 1
                        if self._empty_music_frames >= 25:
                            # Music track truly ended
                            try:
                                self.music_source.cleanup()
                            except Exception:
                                pass
                            self.music_source = None
                            music_callback = self.on_music_end
                            self.on_music_end = None
                        else:
                            # Output silence during temporary buffer gap
                            music_chunk = b'\x00' * self.FRAME_SIZE
                except Exception as e:
                    logger.error(f"Error reading music stream: {e}")
                    try:
                        self.music_source.cleanup()
                    except Exception:
                        pass
                    self.music_source = None
                    music_callback = self.on_music_end
                    self.on_music_end = None

            # If no music frame and no active overlays, playback is finished
            if not music_chunk and not has_overlays:
                if music_callback:
                    try:
                        music_callback(None)
                    except Exception as e:
                        logger.error(f"Error in music on_end callback: {e}")
                return b''

            # 3. Mix streams together
            mixed_buffer = music_chunk if music_chunk else (b'\x00' * self.FRAME_SIZE)
            for ov_chunk in overlay_chunks:
                mixed_buffer = pcm_add(mixed_buffer, ov_chunk)

        # If music ended while overlays are still playing, fire music callback outside the lock
        if music_callback:
            try:
                music_callback(None)
            except Exception as e:
                logger.error(f"Error in music on_end callback: {e}")

        return mixed_buffer

    def cleanup(self):
        """Cleanup all sources."""
        self.stop_all()
