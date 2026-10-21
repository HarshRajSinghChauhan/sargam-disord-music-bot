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

from utils.mixer import AudioMixer, pcm_mul, pcm_add
from utils.database import Database
from cogs.soundboard import (
    validate_audio_file,
    SoundboardView,
    SoundboardButton,
    MAX_DURATION_SECONDS,
    PAGE_SIZE
)


class MockAudioSource(discord.AudioSource):
    """Mock audio source delivering pre-defined 3840-byte 16-bit PCM frames."""
    def __init__(self, frame_count: int, amplitude: int = 5000):
        self.frame_count = frame_count
        self.frames_sent = 0
        self.packet = struct.pack('<2h', amplitude, amplitude) * 960

    def read(self) -> bytes:
        if self.frames_sent >= self.frame_count:
            return b''
        self.frames_sent += 1
        return self.packet

    def cleanup(self):
        pass


class TestSoundboardDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_soundboard.db')
        self.db = Database(db_path=self.db_path)
        await self.db.init_db()

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_soundboard_crud(self):
        guild_id = 999111
        audio_clip = b"RIFF....WAVEfmt ....dataFAKE_AUDIO_DATA_FOR_SOUNDBOARD"

        # 1. Add soundboard sound
        path = await self.db.add_soundboard_sound(
            guild_id=guild_id,
            sound_name="airhorn",
            audio_data=audio_clip,
            emoji="📢",
            volume=80,
            created_by=123456
        )
        self.assertTrue(os.path.exists(path))
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), audio_clip)

        # 2. Get soundboard sound (case insensitive)
        sound = await self.db.get_soundboard_sound(guild_id, "Airhorn")
        self.assertIsNotNone(sound)
        self.assertEqual(sound['sound_name'], "airhorn")
        self.assertEqual(sound['emoji'], "📢")
        self.assertEqual(sound['volume'], 80)
        self.assertEqual(sound['created_by'], 123456)
        self.assertEqual(sound['sound_path'], path)

        # 3. Add second sound
        await self.db.add_soundboard_sound(
            guild_id=guild_id,
            sound_name="bruh",
            audio_data=audio_clip,
            emoji="💀",
            volume=100,
            created_by=123456
        )

        # 4. List sounds
        all_sounds = await self.db.list_soundboard_sounds(guild_id)
        self.assertEqual(len(all_sounds), 2)
        names = [s['sound_name'] for s in all_sounds]
        self.assertEqual(names, ["airhorn", "bruh"])

        # 5. Remove sound
        removed = await self.db.remove_soundboard_sound(guild_id, "airhorn")
        self.assertTrue(removed)
        self.assertFalse(os.path.exists(path))

        # 6. Verify removed
        sound_after = await self.db.get_soundboard_sound(guild_id, "airhorn")
        self.assertIsNone(sound_after)
        remaining = await self.db.list_soundboard_sounds(guild_id)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['sound_name'], "bruh")


class TestSoundboardMixer(unittest.TestCase):
    def test_clear_overlays(self):
        mixer = AudioMixer()
        music = MockAudioSource(frame_count=100, amplitude=10000)
        sfx1 = MockAudioSource(frame_count=50, amplitude=5000)
        sfx2 = MockAudioSource(frame_count=50, amplitude=3000)

        mixer.set_music(music)
        mixer.add_overlay(sfx1, volume=1.0, duck_music=True)
        mixer.add_overlay(sfx2, volume=1.0, duck_music=True)

        self.assertTrue(mixer.has_music())
        self.assertEqual(len(mixer.overlays), 2)

        # Clear overlays
        mixer.clear_overlays()
        self.assertEqual(len(mixer.overlays), 0)
        # Music should still be intact
        self.assertTrue(mixer.has_music())


class TestSoundboardViewPagination(unittest.TestCase):
    def test_pagination_and_buttons(self):
        # Create 45 mock sound items (should result in 3 pages with PAGE_SIZE=20)
        sounds = [
            {"sound_name": f"sound_{i:02d}", "emoji": "🔊", "volume": 100}
            for i in range(45)
        ]

        # Page 0
        view = SoundboardView(cog=None, guild_id=1, user_id=1, sounds=sounds, current_page=0)
        self.assertEqual(view.total_pages, 3)
        self.assertEqual(view.current_page, 0)

        # Check sound button count on Page 0: 20 sound buttons + 5 control buttons = 25 buttons
        sound_buttons = [b for b in view.children if isinstance(b, SoundboardButton)]
        self.assertEqual(len(sound_buttons), 20)
        self.assertEqual(sound_buttons[0].sound_name, "sound_00")
        self.assertEqual(sound_buttons[-1].sound_name, "sound_19")

        # Prev button should be disabled on page 0
        prev_btn = [b for b in view.children if b.label == "◀ Prev"][0]
        self.assertTrue(prev_btn.disabled)

        # Next button should be enabled on page 0
        next_btn = [b for b in view.children if b.label == "Next ▶"][0]
        self.assertFalse(next_btn.disabled)

        # Page 2 (last page: remaining 5 sounds)
        view_last = SoundboardView(cog=None, guild_id=1, user_id=1, sounds=sounds, current_page=2)
        sound_buttons_last = [b for b in view_last.children if isinstance(b, SoundboardButton)]
        self.assertEqual(len(sound_buttons_last), 5)
        self.assertEqual(sound_buttons_last[0].sound_name, "sound_40")
        self.assertEqual(sound_buttons_last[-1].sound_name, "sound_44")

        # Next button should be disabled on last page
        next_btn_last = [b for b in view_last.children if b.label == "Next ▶"][0]
        self.assertTrue(next_btn_last.disabled)


class TestSoundboardAudioValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_wav(self, filename: str, duration_seconds: float) -> str:
        path = os.path.join(self.temp_dir, filename)
        sample_rate = 48000
        total_samples = int(sample_rate * duration_seconds)
        with wave.open(path, 'w') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            data = struct.pack(f'<{total_samples}h', *([1000] * total_samples))
            w.writeframes(data)
        return path

    def test_valid_short_audio(self):
        path = self._create_wav("valid.wav", 3.0)
        valid, err, dur = validate_audio_file(path, max_duration=MAX_DURATION_SECONDS)
        self.assertTrue(valid)
        self.assertIsNone(err)
        self.assertAlmostEqual(dur, 3.0, places=1)

    def test_audio_exceeds_duration(self):
        path = self._create_wav("long.wav", 18.0)
        valid, err, dur = validate_audio_file(path, max_duration=MAX_DURATION_SECONDS)
        self.assertFalse(valid)
        self.assertIn("exceeds the maximum limit", err)

    def test_corrupt_file(self):
        corrupt_path = os.path.join(self.temp_dir, "corrupt.mp3")
        with open(corrupt_path, 'wb') as f:
            f.write(b"not an audio file at all")
        valid, err, dur = validate_audio_file(corrupt_path, max_duration=MAX_DURATION_SECONDS)
        self.assertFalse(valid)


if __name__ == '__main__':
    unittest.main()
