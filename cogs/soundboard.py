import os
import math
import time
import shutil
import logging
import asyncio
from typing import Optional, List, Tuple, Dict, Any

import discord
from discord.ext import commands
from discord import app_commands

from utils.database import db, SOUNDBOARD_DIR
from utils.mixer import AudioMixer

logger = logging.getLogger('sargam.soundboard')

# Validation constants
ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.ogg'}
ALLOWED_MIME_TYPES = {
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/ogg', 'application/ogg', 'audio/vorbis'
}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB
MAX_DURATION_SECONDS = 15.0             # 15 seconds max duration for soundboard clips
PAGE_SIZE = 20                          # 4 rows of 5 buttons max


def validate_audio_file(file_path: str, max_duration: float = MAX_DURATION_SECONDS) -> Tuple[bool, Optional[str], float]:
    """
    Validates that the file is readable audio and within the maximum duration limit.
    """
    try:
        import mutagen
        audio = mutagen.File(file_path)
        if audio is None or not hasattr(audio, 'info') or audio.info is None:
            return False, "Invalid or unreadable audio file. Supported formats: MP3, WAV, OGG.", 0.0

        duration = getattr(audio.info, 'length', 0.0)
        if duration <= 0:
            return False, "Could not determine audio duration or audio file is empty.", 0.0

        if duration > max_duration:
            return False, f"Audio duration ({duration:.1f}s) exceeds the maximum limit of {int(max_duration)}s.", duration

        return True, None, duration
    except Exception as e:
        logger.error(f"Audio validation failed: {e}")
        return False, f"Failed to inspect audio metadata: {str(e)}", 0.0


def get_ffmpeg_kwargs() -> dict:
    """Returns FFmpeg arguments, detecting local binary if present."""
    kwargs = {
        'options': '-vn -filter:a "aresample=48000" -ar 48000 -ac 2'
    }
    local_ffmpeg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        kwargs['executable'] = local_ffmpeg
    return kwargs


class SoundboardButton(discord.ui.Button):
    """A clickable soundboard button representing one audio clip."""
    def __init__(self, sound_name: str, emoji: Optional[str] = None, row: int = 0):
        parsed_emoji = None
        if emoji:
            try:
                parsed_emoji = discord.PartialEmoji.from_str(emoji.strip())
            except Exception:
                parsed_emoji = None

        # Truncate label to 20 chars so it cleanly fits on Discord button grids
        display_label = sound_name[:20]

        super().__init__(
            label=display_label,
            emoji=parsed_emoji,
            style=discord.ButtonStyle.secondary,
            row=row
        )
        self.sound_name = sound_name

    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        await self.view.handle_sound_click(interaction, self.sound_name)


class SoundboardView(discord.ui.View):
    """Interactive paginated Discord View for the soundboard."""
    def __init__(
        self,
        cog: 'Soundboard',
        guild_id: int,
        user_id: int,
        sounds: List[Dict[str, Any]],
        current_page: int = 0,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.sounds = sounds
        self.current_page = current_page
        self.last_status = "Tap any sound button below to play."
        self.build_view()

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.sounds) / PAGE_SIZE))

    def build_view(self):
        """Builds or rebuilds the 5-row button grid according to current page."""
        self.clear_items()
        total_p = self.total_pages
        self.current_page = max(0, min(self.current_page, total_p - 1))

        if not self.sounds:
            # Empty state: Add close button
            close_btn = discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.secondary,
                row=0
            )
            close_btn.callback = self._on_close_clicked
            self.add_item(close_btn)
            return

        # Sliced sounds for current page (up to 20 sounds across rows 0-3)
        start_idx = self.current_page * PAGE_SIZE
        page_sounds = self.sounds[start_idx: start_idx + PAGE_SIZE]

        for i, sound in enumerate(page_sounds):
            row_idx = i // 5
            btn = SoundboardButton(
                sound_name=sound['sound_name'],
                emoji=sound.get('emoji'),
                row=row_idx
            )
            self.add_item(btn)

        # Row 4: Controls and Navigation Bar
        prev_btn = discord.ui.Button(
            label="◀ Prev",
            style=discord.ButtonStyle.primary,
            row=4,
            disabled=(self.current_page == 0)
        )
        prev_btn.callback = self._on_prev_clicked
        self.add_item(prev_btn)

        page_indicator = discord.ui.Button(
            label=f"{self.current_page + 1}/{total_p}",
            style=discord.ButtonStyle.secondary,
            row=4,
            disabled=True
        )
        self.add_item(page_indicator)

        next_btn = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.primary,
            row=4,
            disabled=(self.current_page >= total_p - 1)
        )
        next_btn.callback = self._on_next_clicked
        self.add_item(next_btn)

        stop_btn = discord.ui.Button(
            label="⏹ Stop",
            style=discord.ButtonStyle.danger,
            row=4
        )
        stop_btn.callback = self._on_stop_clicked
        self.add_item(stop_btn)

        close_btn = discord.ui.Button(
            label="❌ Close",
            style=discord.ButtonStyle.secondary,
            row=4
        )
        close_btn.callback = self._on_close_clicked
        self.add_item(close_btn)

    def create_embed(self) -> discord.Embed:
        """Generates the soundboard status and control panel embed."""
        embed = discord.Embed(
            title="🔊 Sargam Soundboard",
            color=discord.Color.from_rgb(88, 101, 242)
        )

        if not self.sounds:
            embed.description = (
                "ℹ️ **No soundboard sounds found in this server!**\n\n"
                "Upload your custom sounds using:\n"
                "`/soundboard add name:<name> sound:<file> [emoji:<emoji>]`"
            )
            return embed

        embed.description = (
            f"**Total Sounds:** {len(self.sounds)} | **Page:** {self.current_page + 1}/{self.total_pages}\n"
            f"**Status:** {self.last_status}"
        )
        embed.set_footer(text="Tip: Click any button to play sound into your voice channel.")
        return embed

    async def handle_sound_click(self, interaction: discord.Interaction, sound_name: str):
        """Handles a user tapping a sound button."""
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "❌ You must be connected to a voice channel to play soundboard audio!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        success, msg = await self.cog.play_sound(interaction.guild, member, sound_name)
        if success:
            self.last_status = f"▶️ Playing: **{sound_name}**"
        else:
            self.last_status = f"⚠️ {msg}"

        try:
            await interaction.edit_original_response(embed=self.create_embed(), view=self)
        except Exception as e:
            logger.debug(f"Could not edit interaction response after sound click: {e}")

    async def _on_prev_clicked(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.build_view()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def _on_next_clicked(self, interaction: discord.Interaction):
        self.current_page += 1
        self.build_view()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def _on_stop_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if interaction.guild:
            await self.cog.stop_sound(interaction.guild)
        self.last_status = "⏹ Stopped soundboard playback."
        try:
            await interaction.edit_original_response(embed=self.create_embed(), view=self)
        except Exception:
            pass

    async def _on_close_clicked(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

    async def on_timeout(self):
        """Disable all buttons when interaction view times out."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


class Soundboard(commands.Cog):
    """Custom Server-Wide Unlimited Soundboard with Ephemeral UI."""

    # Slash command group for soundboard management
    soundboard_group = app_commands.Group(name="soundboard", description="Soundboard controls and management")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> idle_disconnect_task
        self.idle_tasks = {}

    def cog_unload(self):
        for task in self.idle_tasks.values():
            task.cancel()

    def _get_music_state(self, guild_id: int):
        music_cog = self.bot.get_cog('Music')
        if music_cog:
            return music_cog.get_state(guild_id)
        return None

    def _schedule_idle_check(self, guild_id: int, channel: discord.VoiceChannel, delay: int = 120):
        """Disconnects the bot after idle delay if no music and no queue."""
        if guild_id in self.idle_tasks:
            self.idle_tasks[guild_id].cancel()

        async def _disconnect_if_idle():
            try:
                await asyncio.sleep(delay)
                state = self._get_music_state(guild_id)
                if state and state.voice_client and state.voice_client.is_connected():
                    if not state.mixer.has_music() and len(state.queue) == 0 and not state.mixer.has_overlays():
                        await state.voice_client.disconnect()
                        state.voice_client = None
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error in soundboard idle check disconnect: {e}")
            finally:
                self.idle_tasks.pop(guild_id, None)

        self.idle_tasks[guild_id] = self.bot.loop.create_task(_disconnect_if_idle())

    # ==================== AUDIO PLAYBACK ENGINE ====================

    async def play_sound(self, guild: discord.Guild, member: discord.Member, sound_name: str) -> Tuple[bool, str]:
        """
        Plays a soundboard clip into the voice channel.
        Mixes with current music track or connects on demand.
        """
        if not member.voice or not member.voice.channel:
            return False, "You must be in a voice channel."

        target_channel = member.voice.channel
        state = self._get_music_state(guild.id)
        if not state:
            return False, "Music subsystem is not initialized."

        # Fetch sound from DB
        sound = await db.get_soundboard_sound(guild.id, sound_name)
        if not sound or not sound.get('sound_path') or not os.path.exists(sound['sound_path']):
            return False, f"Sound `{sound_name}` was not found."

        # Voice connection coordination
        if state.voice_client and state.voice_client.is_connected():
            if state.voice_client.channel.id != target_channel.id:
                # If playing music in another channel with active human listeners, do not interrupt
                non_bot_members = [m for m in state.voice_client.channel.members if not m.bot]
                if (state.mixer.has_music() or len(state.queue) > 0) and len(non_bot_members) > 0:
                    return False, f"Bot is currently active in **{state.voice_client.channel.name}**."
                try:
                    await state.voice_client.move_to(target_channel)
                except Exception as e:
                    logger.error(f"Failed to move to VC {target_channel.name}: {e}")
                    return False, f"Failed to join voice channel: {e}"
        else:
            perms = target_channel.permissions_for(guild.me)
            if not (perms.connect and perms.speak):
                return False, f"Bot lacks Connect or Speak permissions in **{target_channel.name}**."

            try:
                state.voice_client = await target_channel.connect(timeout=10.0)
                self._schedule_idle_check(guild.id, target_channel, delay=120)
            except Exception as e:
                logger.error(f"Failed to connect to VC {target_channel.name}: {e}")
                return False, f"Could not connect to voice channel: {e}"

        # Play through AudioMixer overlay
        try:
            settings = await db.get_guild_settings(guild.id)
            state.mixer.duck_volume = float(settings.get('duck_volume', 0.25))

            ffmpeg_kwargs = get_ffmpeg_kwargs()
            sfx = discord.FFmpegPCMAudio(sound['sound_path'], **ffmpeg_kwargs)
            vol = float(sound.get('volume', 100)) / 100.0

            state.mixer.add_overlay(sfx, volume=vol, duck_music=True)

            if not state.voice_client.is_playing():
                try:
                    state.voice_client.play(state.mixer)
                except discord.ClientException:
                    pass

            return True, f"Playing `{sound['sound_name']}`"
        except Exception as e:
            logger.error(f"Error playing soundboard audio: {e}")
            return False, f"Audio error: {e}"

    async def stop_sound(self, guild: discord.Guild):
        """Stops any active soundboard overlay sounds without interrupting music."""
        state = self._get_music_state(guild.id)
        if state and state.mixer:
            state.mixer.clear_overlays()

    # ==================== AUTOCOMPLETE HELPERS ====================

    async def sound_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Provides fast autocomplete for soundboard sounds in the current server."""
        if not interaction.guild_id:
            return []
        try:
            sounds = await db.list_soundboard_sounds(interaction.guild_id)
            choices = []
            curr_lower = current.strip().lower()
            for s in sounds:
                name = s['sound_name']
                if curr_lower in name.lower():
                    emoji_prefix = f"{s['emoji']} " if s.get('emoji') else ""
                    label = f"{emoji_prefix}{name}"[:100]
                    choices.append(app_commands.Choice(name=label, value=name))
                if len(choices) >= 25:
                    break
            return choices
        except Exception as e:
            logger.debug(f"Autocomplete error: {e}")
            return []

    # ==================== SHORTCUT COMMAND: /sb ====================

    @app_commands.command(name="sb", description="Open the soundboard pad or trigger a sound instantly")
    @app_commands.describe(
        sound="(Optional) Name of the sound to play immediately",
        public="(Optional) Set to True to share the soundboard pad with everyone in chat (default: False/Private)"
    )
    async def sb_shortcut(
        self,
        interaction: discord.Interaction,
        sound: Optional[str] = None,
        public: Optional[bool] = False
    ):
        if not interaction.guild_id or not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        is_ephemeral = not public

        # If a specific sound was requested, play directly
        if sound:
            member = interaction.user
            if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
                await interaction.response.send_message(
                    "❌ You must be connected to a voice channel to play sounds!",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=is_ephemeral)
            success, msg = await self.play_sound(interaction.guild, member, sound)
            if success:
                await interaction.followup.send(f"🔊 {interaction.user.mention} played sound **{sound}**!")
            else:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        # Otherwise open the interactive UI pad
        sounds = await db.list_soundboard_sounds(interaction.guild_id)
        view = SoundboardView(
            cog=self,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            sounds=sounds
        )
        await interaction.response.send_message(
            embed=view.create_embed(),
            view=view,
            ephemeral=is_ephemeral
        )

    @sb_shortcut.autocomplete("sound")
    async def sb_shortcut_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.sound_autocomplete(interaction, current)

    # ==================== SOUNDBOARD GROUP COMMANDS ====================

    @soundboard_group.command(name="open", description="Open the interactive soundboard popup pad")
    @app_commands.describe(public="(Optional) Set to True to display for everyone in chat (default: False/Private)")
    async def sb_open(self, interaction: discord.Interaction, public: Optional[bool] = False):
        if not interaction.guild_id:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        sounds = await db.list_soundboard_sounds(interaction.guild_id)
        view = SoundboardView(
            cog=self,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            sounds=sounds
        )
        await interaction.response.send_message(
            embed=view.create_embed(),
            view=view,
            ephemeral=not public
        )

    @soundboard_group.command(name="play", description="Play a specific soundboard clip into your voice channel")
    @app_commands.describe(name="Name of the sound to play")
    async def sb_play(self, interaction: discord.Interaction, name: str):
        if not interaction.guild or not interaction.guild_id:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "❌ You must be connected to a voice channel to play sounds!",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)
        success, msg = await self.play_sound(interaction.guild, member, name)
        if success:
            await interaction.followup.send(f"🔊 {interaction.user.mention} played sound **{name}**!")
        else:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)

    @sb_play.autocomplete("name")
    async def sb_play_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.sound_autocomplete(interaction, current)

    @soundboard_group.command(name="add", description="Add a new sound to this server's unlimited soundboard")
    @app_commands.describe(
        name="Unique identifier name for this sound (letters, numbers, hyphens, underscores)",
        sound="The audio file to upload (MP3, WAV, or OGG, max 15s & 5MB)",
        emoji="(Optional) Emoji to display on the soundboard button (e.g. 📢, 💀)",
        volume="(Optional) Playback volume from 1% to 100% (default: 100%)"
    )
    async def sb_add(
        self,
        interaction: discord.Interaction,
        name: str,
        sound: discord.Attachment,
        emoji: Optional[str] = None,
        volume: Optional[app_commands.Range[int, 1, 100]] = 100
    ):
        if not interaction.guild_id:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        clean_name = name.strip().lower()
        # Validation: valid name
        safe_check = clean_name.replace('_', '').replace('-', '')
        if not safe_check.isalnum() or len(clean_name) > 30:
            await interaction.response.send_message(
                "❌ Sound name must be alphanumeric (letters, numbers, underscores, hyphens) and 1–30 characters long.",
                ephemeral=True
            )
            return

        # Validation: extension
        ext = os.path.splitext(sound.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            await interaction.response.send_message(
                f"❌ Unsupported format `{ext}`. Please upload an **MP3**, **WAV**, or **OGG** audio file.",
                ephemeral=True
            )
            return

        # Validation: file size
        if sound.size > MAX_FILE_SIZE_BYTES:
            size_mb = sound.size / (1024 * 1024)
            await interaction.response.send_message(
                f"❌ File size too large ({size_mb:.1f} MB). Maximum allowed size is **{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        # Temporary download to validate audio metadata
        guild_dir = os.path.join(SOUNDBOARD_DIR, str(interaction.guild_id))
        os.makedirs(guild_dir, exist_ok=True)
        temp_file_path = os.path.join(guild_dir, f"temp_{clean_name}_{int(time.time())}{ext}")

        try:
            audio_bytes = await sound.read()
            with open(temp_file_path, 'wb') as f:
                f.write(audio_bytes)

            is_valid, error_msg, duration = validate_audio_file(temp_file_path, max_duration=MAX_DURATION_SECONDS)
            if not is_valid:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                await interaction.followup.send(f"❌ {error_msg}")
                return

            # Clean up temp file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

            # Store in database
            await db.add_soundboard_sound(
                guild_id=interaction.guild_id,
                sound_name=clean_name,
                audio_data=audio_bytes,
                emoji=emoji.strip() if emoji else None,
                volume=volume,
                created_by=interaction.user.id
            )

            emoji_display = f"{emoji.strip()} " if emoji else ""
            embed = discord.Embed(
                title="✅ Sound Added to Soundboard",
                description=(
                    f"**Sound:** {emoji_display}`{clean_name}`\n"
                    f"**Duration:** {duration:.1f}s\n"
                    f"**Volume:** {volume}%\n"
                    f"**Added By:** {interaction.user.mention}\n\n"
                    f"Type `/sb` to open the pad or `/sb sound:{clean_name}` to play it immediately!"
                ),
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error adding soundboard sound: {e}")
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            await interaction.followup.send(f"❌ An error occurred while saving the sound: {e}")

    @soundboard_group.command(name="remove", description="Remove a sound from this server's soundboard")
    @app_commands.describe(name="Name of the sound to remove")
    async def sb_remove(self, interaction: discord.Interaction, name: str):
        if not interaction.guild_id:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        clean_name = name.strip().lower()
        existing = await db.get_soundboard_sound(interaction.guild_id, clean_name)
        if not existing:
            await interaction.response.send_message(f"❌ Sound `{clean_name}` does not exist.", ephemeral=True)
            return

        # Check permissions: Creator or Manage Server
        perms = interaction.user.guild_permissions
        if existing.get('created_by') and existing['created_by'] != interaction.user.id:
            if not (perms.manage_guild or perms.administrator):
                await interaction.response.send_message(
                    "❌ You can only delete sounds you uploaded yourself unless you have **Manage Server** permissions.",
                    ephemeral=True
                )
                return

        await db.remove_soundboard_sound(interaction.guild_id, clean_name)
        await interaction.response.send_message(f"🗑️ Successfully removed sound **`{clean_name}`** from the soundboard.")

    @sb_remove.autocomplete("name")
    async def sb_remove_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.sound_autocomplete(interaction, current)

    @soundboard_group.command(name="list", description="List all available soundboard sounds in this server")
    async def sb_list(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        sounds = await db.list_soundboard_sounds(interaction.guild_id)
        if not sounds:
            await interaction.response.send_message(
                "ℹ️ There are no soundboard sounds in this server yet.\nUse `/soundboard add` to add some!",
                ephemeral=True
            )
            return

        lines = []
        for s in sounds:
            emoji_str = f"{s['emoji']} " if s.get('emoji') else "• "
            lines.append(f"{emoji_str}**`{s['sound_name']}`** (Vol: {s['volume']}%)")

        # Split into chunks of 30 if list is huge
        chunk = "\n".join(lines[:30])
        total_remaining = len(lines) - 30 if len(lines) > 30 else 0

        embed = discord.Embed(
            title=f"🔊 Server Soundboard ({len(sounds)} sounds)",
            description=chunk,
            color=discord.Color.blurple()
        )
        if total_remaining > 0:
            embed.set_footer(text=f"...and {total_remaining} more. Use /sb to browse with buttons!")
        else:
            embed.set_footer(text="Use /sb to open the interactive button pad!")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Soundboard(bot))
