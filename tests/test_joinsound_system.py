import os
import io
import time
import wave
import struct
import shutil
import asyncio
import unittest
import tempfile
import discord

from utils.mixer import AudioMixer, OverlaySound, pcm_mul, pcm_add
from utils.database import Database
from cogs.joinsound import validate_audio_file, MAX_DURATION_SECONDS


class MockAudioSource(discord.AudioSource):
    """Mock audio source delivering pre-defined 3840-byte 16-bit PCM frames."""
    def __init__(self, frame_count: int, amplitude: int = 5000):
        self.frame_count = frame_count
        self.frames_sent = 0
        # 16-bit stereo: 960 samples per channel = 1920 samples = 3840 bytes
        self.packet = struct.pack('<2h', amplitude, amplitude) * 960

    def read(self) -> bytes:
        if self.frames_sent >= self.frame_count:
            return b''
        self.frames_sent += 1
        return self.packet

    def cleanup(self):
        pass


class TestAudioMixer(unittest.TestCase):
    def test_pcm_operations(self):
        # 1. Test volume scaling
        frame = struct.pack('<2h', 1000, -1000) * 960
        scaled = pcm_mul(frame, 0.5)
        self.assertEqual(len(scaled), 3840)
        s1, s2 = struct.unpack_from('<2h', scaled, 0)
        self.assertEqual(s1, 500)
        self.assertEqual(s2, -500)

        # 2. Test saturation addition
        f1 = struct.pack('<2h', 20000, 25000) * 960
        f2 = struct.pack('<2h', 20000, 10000) * 960
        added = pcm_add(f1, f2)
        s1, s2 = struct.unpack_from('<2h', added, 0)
        self.assertEqual(s1, 32767)  # Clamped to int16 max
        self.assertEqual(s2, 32767)  # Clamped

    def test_music_only_playback(self):
        mixer = AudioMixer()
        music = MockAudioSource(frame_count=5, amplitude=4000)
        ended = False

        def on_end(err):
            nonlocal ended
            ended = True

        mixer.set_music(music, on_end=on_end)
        self.assertTrue(mixer.has_music())

        frames_read = 0
        while True:
            chunk = mixer.read()
            if not chunk:
                break
            frames_read += 1
            self.assertEqual(len(chunk), 3840)

        self.assertEqual(frames_read, 5)
        self.assertTrue(ended)
        self.assertFalse(mixer.has_music())

    def test_simultaneous_mixing_and_ducking(self):
        mixer = AudioMixer()
        mixer.music_volume = 1.0
        mixer.duck_volume = 0.25

        # 6 frames of music
        music = MockAudioSource(frame_count=6, amplitude=10000)
        # 3 frames of join sound
        sfx = MockAudioSource(frame_count=3, amplitude=8000)

        mixer.set_music(music)
        mixer.add_overlay(sfx, volume=1.0, duck_music=True)

        frames = []
        while True:
            chunk = mixer.read()
            if not chunk:
                break
            frames.append(chunk)

        # 6 frames total (since music had 6 frames and sfx had 3)
        self.assertEqual(len(frames), 6)

        # During first 3 frames, ducking should be active:
        # music (10000 * 0.25 = 2500) + sfx (8000 * 1.0 = 8000) = 10500
        for i in range(3):
            s1, _ = struct.unpack_from('<2h', frames[i], 0)
            self.assertEqual(s1, 10500)

        # During last 3 frames, sfx is done; music should restore to full volume (10000)
        for i in range(3, 6):
            s1, _ = struct.unpack_from('<2h', frames[i], 0)
            self.assertEqual(s1, 10000)

    def test_multiple_simultaneous_overlays(self):
        mixer = AudioMixer()
        mixer.music_volume = 1.0
        mixer.duck_volume = 0.5

        music = MockAudioSource(frame_count=4, amplitude=4000)
        sfx1 = MockAudioSource(frame_count=2, amplitude=3000)
        sfx2 = MockAudioSource(frame_count=2, amplitude=2000)

        mixer.set_music(music)
        mixer.add_overlay(sfx1, volume=1.0)
        mixer.add_overlay(sfx2, volume=1.0)

        # Frame 0: music ducked (4000 * 0.5 = 2000) + sfx1 (3000) + sfx2 (2000) = 7000
        chunk0 = mixer.read()
        s1, _ = struct.unpack_from('<2h', chunk0, 0)
        self.assertEqual(s1, 7000)

    def test_pause_resume_fallback_mode(self):
        mixer = AudioMixer()
        mixer.music_volume = 1.0
        mixer.pause_resume_mode = True  # Enable pause-resume fallback

        music = MockAudioSource(frame_count=4, amplitude=5000)
        sfx = MockAudioSource(frame_count=2, amplitude=8000)

        mixer.set_music(music)
        mixer.add_overlay(sfx, volume=1.0)

        # Frame 0 & 1: Music paused, only SFX plays
        chunk0 = mixer.read()
        s1, _ = struct.unpack_from('<2h', chunk0, 0)
        self.assertEqual(s1, 8000)

        chunk1 = mixer.read()
        s1, _ = struct.unpack_from('<2h', chunk1, 0)
        self.assertEqual(s1, 8000)

        # Frame 2: SFX done, music resumes (music frame 0!)
        chunk2 = mixer.read()
        s1, _ = struct.unpack_from('<2h', chunk2, 0)
        self.assertEqual(s1, 5000)


class TestDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_sargam.db')
        self.db = Database(self.db_path)
        await self.db.init_db()

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_join_sound_crud_and_server_isolation(self):
        fake_audio_a = b"RIFF....WAVEfmt ....dataFAKE_AUDIO_A"
        fake_audio_b = b"RIFF....WAVEfmt ....dataFAKE_AUDIO_B"
        fake_audio_a2 = b"RIFF....WAVEfmt ....dataFAKE_AUDIO_A2"

        # 1. Add sound for User 1 in Guild A
        path_a = await self.db.set_join_sound(
            guild_id=101,
            user_id=201,
            sound_name="harsh_a.mp3",
            audio_data=fake_audio_a,
            volume=60,
            enabled=True
        )
        self.assertTrue(os.path.exists(path_a))

        # 2. Add sound for User 1 in Guild B (Different server)
        path_b = await self.db.set_join_sound(
            guild_id=102,
            user_id=201,
            sound_name="harsh_b.mp3",
            audio_data=fake_audio_b,
            volume=80,
            enabled=True
        )
        self.assertTrue(os.path.exists(path_b))

        # 3. Retrieve User 1 in Guild A
        sound_a = await self.db.get_join_sound(101, 201)
        self.assertIsNotNone(sound_a)
        self.assertEqual(sound_a['sound_name'], "harsh_a.mp3")
        self.assertEqual(sound_a['volume'], 60)
        self.assertTrue(os.path.exists(sound_a['sound_path']))

        # 4. Retrieve User 1 in Guild B
        sound_b = await self.db.get_join_sound(102, 201)
        self.assertIsNotNone(sound_b)
        self.assertEqual(sound_b['sound_name'], "harsh_b.mp3")
        self.assertEqual(sound_b['volume'], 80)
        self.assertTrue(os.path.exists(sound_b['sound_path']))

        # 5. Update sound in Guild A
        path_a2 = await self.db.set_join_sound(
            guild_id=101,
            user_id=201,
            sound_name="harsh_a_v2.mp3",
            audio_data=fake_audio_a2,
            volume=70,
            enabled=True
        )
        self.assertTrue(os.path.exists(path_a2))

        # 6. List sounds for Guild A
        sounds = await self.db.list_guild_join_sounds(101)
        self.assertEqual(len(sounds), 1)
        self.assertEqual(sounds[0]['sound_name'], "harsh_a_v2.mp3")

        # 7. Remove sound
        removed = await self.db.remove_join_sound(101, 201)
        self.assertTrue(removed)

        # Guild A should now be empty, but Guild B untouched
        self.assertIsNone(await self.db.get_join_sound(101, 201))
        self.assertIsNotNone(await self.db.get_join_sound(102, 201))
        self.assertIsNotNone(await self.db.get_join_sound(102, 201))

    async def test_guild_settings(self):
        # Default settings
        defaults = await self.db.get_guild_settings(999)
        self.assertEqual(defaults['cooldown_seconds'], 30)
        self.assertEqual(defaults['duck_volume'], 0.25)
        self.assertEqual(defaults['auto_connect'], 1)
        self.assertEqual(defaults['enabled'], 1)

        # Update settings
        updated = await self.db.set_guild_settings(
            guild_id=999,
            cooldown_seconds=45,
            duck_volume=0.10,
            auto_connect=False,
            enabled=True
        )
        self.assertEqual(updated['cooldown_seconds'], 45)
        self.assertEqual(updated['duck_volume'], 0.10)
        self.assertEqual(updated['auto_connect'], 0)

        # Verify persisted
        recheck = await self.db.get_guild_settings(999)
        self.assertEqual(recheck['cooldown_seconds'], 45)


class TestAudioValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_synthetic_wav(self, filename: str, duration_sec: float) -> str:
        path = os.path.join(self.temp_dir, filename)
        sample_rate = 44100
        total_samples = int(sample_rate * duration_sec)
        with wave.open(path, 'w') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            data = struct.pack(f'<{total_samples}h', *([1000] * total_samples))
            w.writeframes(data)
        return path

    def test_valid_short_audio(self):
        wav_path = self._create_synthetic_wav("short.wav", duration_sec=3.0)
        is_valid, err, duration = validate_audio_file(wav_path, max_duration=10.0)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertAlmostEqual(duration, 3.0, delta=0.1)

    def test_excessive_duration_audio_rejected(self):
        wav_path = self._create_synthetic_wav("long.wav", duration_sec=15.0)
        is_valid, err, duration = validate_audio_file(wav_path, max_duration=10.0)
        self.assertFalse(is_valid)
        self.assertIn("exceeds the maximum limit", err)

    def test_corrupt_file_rejected(self):
        corrupt_path = os.path.join(self.temp_dir, "corrupt.mp3")
        with open(corrupt_path, "wb") as f:
            f.write(b"NOT_REAL_AUDIO_DATA_GARBAGE")
        is_valid, err, duration = validate_audio_file(corrupt_path, max_duration=10.0)
        self.assertFalse(is_valid)


if __name__ == '__main__':
    unittest.main()
