import os
import time
import logging
import asyncio
from typing import Optional, Tuple
import discord
from discord.ext import commands
from discord import app_commands

from utils.database import db, SOUNDS_DIR
from utils.mixer import AudioMixer

logger = logging.getLogger('sargam.joinsound')

# Validation constants
ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.ogg'}
ALLOWED_MIME_TYPES = {
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/ogg', 'application/ogg', 'audio/vorbis'
}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_DURATION_SECONDS = 10.0           # 10 seconds max duration


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


class JoinSound(commands.Cog):
    """Custom Voice Channel Join Sound System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, user_id) -> last_triggered_timestamp
        self.cooldowns = {}
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
        """Disconnects the bot after idle delay if no music and no humans or inactive."""
        if guild_id in self.idle_tasks:
            self.idle_tasks[guild_id].cancel()

        async def _disconnect_if_idle():
            try:
                await asyncio.sleep(delay)
                state = self._get_music_state(guild_id)
                if state and state.voice_client and state.voice_client.is_connected():
                    # Only disconnect if not playing music and queue is empty
                    if not state.mixer.has_music() and len(state.queue) == 0:
                        await state.voice_client.disconnect()
                        state.voice_client = None
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error in idle check disconnect: {e}")
            finally:
                self.idle_tasks.pop(guild_id, None)

        self.idle_tasks[guild_id] = self.bot.loop.create_task(_disconnect_if_idle())

    # ==================== VOICE STATE LISTENER ====================

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # Case 10: Ignore bot itself and other bots
        if member.bot:
            return

        guild = member.guild
        state = self._get_music_state(guild.id)

        # Case 3 & Case 9: User leaves VC
        if after.channel is None:
            # If user left the channel Sargam is currently in, check if everyone left
            if state and state.voice_client and state.voice_client.channel == before.channel:
                human_members = [m for m in before.channel.members if not m.bot]
                if len(human_members) == 0:
                    # Everyone left: disconnect and clean up
                    logger.info(f"Everyone left {before.channel.name}. Auto-disconnecting.")
                    state.mixer.stop_all()
                    state.queue.clear()
                    state.loop = False
                    await state.voice_client.disconnect()
                    state.voice_client = None
            return

        # Same channel update (mute, deafen, camera, screen-share) -> do nothing
        if before.channel == after.channel:
            return

        # Case 1 & Case 2: User joined or moved to a voice channel
        target_channel = after.channel
        guild_settings = await db.get_guild_settings(guild.id)
        if not guild_settings.get('enabled', 1):
            return

        # Case 7: User has no configured sound
        sound_record = await db.get_join_sound(guild.id, member.id)
        if not sound_record or not sound_record.get('enabled', 1):
            return

        sound_path = sound_record['sound_path']
        if not os.path.exists(sound_path):
            logger.warning(f"Join sound file not found: {sound_path}")
            return

        # Anti-spam / Cooldown check
        cooldown_sec = guild_settings.get('cooldown_seconds', 30)
        cooldown_key = (guild.id, member.id)
        now = time.time()
        last_played = self.cooldowns.get(cooldown_key, 0)
        if now - last_played < cooldown_sec:
            logger.info(f"User {member.display_name} joined within cooldown ({now - last_played:.1f}s < {cooldown_sec}s). Skipping join sound.")
            return

        # Connection handling
        if state is None:
            return

        # If Sargam is in another VC:
        if state.voice_client and state.voice_client.is_connected():
            if state.voice_client.channel != target_channel:
                # Case 5: Sargam is in another VC playing music -> do NOT interrupt
                if state.mixer.has_music() or len(state.queue) > 0:
                    return
                # If idle in another VC, do not move unless auto_connect is on
                if not guild_settings.get('auto_connect', 1):
                    return
                try:
                    await state.voice_client.move_to(target_channel)
                except Exception as e:
                    logger.error(f"Failed to move to VC {target_channel.name}: {e}")
                    return
        else:
            # Case 8: Sargam is not connected -> join only if allowed and permitted
            if not guild_settings.get('auto_connect', 1):
                return

            perms = target_channel.permissions_for(guild.me)
            if not (perms.connect and perms.speak):
                logger.warning(f"Bot lacks Connect or Speak permissions in {target_channel.name}")
                return

            try:
                state.voice_client = await target_channel.connect(timeout=10.0)
                # If bot connected just for the join sound, schedule idle disconnect
                self._schedule_idle_check(guild.id, target_channel, delay=120)
            except Exception as e:
                logger.error(f"Failed to connect to VC {target_channel.name}: {e}")
                return

        # Record cooldown
        self.cooldowns[cooldown_key] = now

        # Play join sound through AudioMixer
        try:
            duck_vol = float(guild_settings.get('duck_volume', 0.25))
            state.mixer.duck_volume = duck_vol

            ffmpeg_options = {
                'options': '-vn -filter:a "aresample=48000" -ar 48000 -ac 2'
            }
            sfx_source = discord.FFmpegPCMAudio(sound_path, **ffmpeg_options)
            user_vol = sound_record['volume'] / 100.0

            # Add overlay to mixer
            state.mixer.add_overlay(sfx_source, volume=user_vol, duck_music=True)

            # Ensure voice client is actively streaming the mixer
            if not state.voice_client.is_playing():
                try:
                    state.voice_client.play(state.mixer)
                except discord.ClientException:
                    pass
        except Exception as e:
            logger.error(f"Error playing join sound for {member.display_name}: {e}")

    # ==================== SLASH COMMANDS ====================

    @app_commands.command(name="setjoinsound", description="Assign a custom voice channel join sound")
    @app_commands.describe(
        sound="The audio file to play when joining (MP3, WAV, or OGG, max 10s & 5MB)",
        user="(Optional) Member to assign sound to. Requires Manage Server permission if not yourself",
        volume="(Optional) Playback volume from 1% to 100% (default: 50%)",
        enabled="(Optional) Whether this join sound is active (default: True)"
    )
    async def setjoinsound(
        self,
        interaction: discord.Interaction,
        sound: discord.Attachment,
        user: Optional[discord.Member] = None,
        volume: Optional[app_commands.Range[int, 1, 100]] = 50,
        enabled: Optional[bool] = True
    ):
        target_user = user or interaction.user

        # Permissions check
        if target_user.id != interaction.user.id:
            perms = interaction.user.guild_permissions
            if not (perms.manage_guild or perms.administrator):
                await interaction.response.send_message(
                    "❌ You need the **Manage Server** permission to configure join sounds for other members.",
                    ephemeral=True
                )
                return

        # Attachment validation: extension
        ext = os.path.splitext(sound.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            await interaction.response.send_message(
                f"❌ Unsupported format `{ext}`. Please upload an **MP3**, **WAV**, or **OGG** audio file.",
                ephemeral=True
            )
            return

        # Attachment validation: file size
        if sound.size > MAX_FILE_SIZE_BYTES:
            size_mb = sound.size / (1024 * 1024)
            await interaction.response.send_message(
                f"❌ File size too large ({size_mb:.1f} MB). Maximum allowed size is **{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        # Ensure guild directory exists
        guild_dir = os.path.join(SOUNDS_DIR, str(interaction.guild_id))
        os.makedirs(guild_dir, exist_ok=True)

        target_file_path = os.path.join(guild_dir, f"{target_user.id}_{int(time.time())}{ext}")

        try:
            # Download attachment bytes
            audio_bytes = await sound.read()
            with open(target_file_path, 'wb') as f:
                f.write(audio_bytes)

            # Validate audio format & duration
            is_valid, error_msg, duration = validate_audio_file(target_file_path, max_duration=MAX_DURATION_SECONDS)
            if not is_valid:
                if os.path.exists(target_file_path):
                    os.remove(target_file_path)
                await interaction.followup.send(f"❌ {error_msg}")
                return

            # Store in database (with binary audio_data for persistent cloud/Neon storage)
            await db.set_join_sound(
                guild_id=interaction.guild_id,
                user_id=target_user.id,
                sound_name=sound.filename,
                audio_data=audio_bytes,
                volume=volume,
                enabled=enabled
            )

            # Respond with UX format matching requirements
            response_text = (
                f"✅ **Join sound configured!**\n\n"
                f"👤 **User:** {target_user.mention}\n"
                f"🔊 **Sound:** `{sound.filename}` ({duration:.1f}s)\n"
                f"🔉 **Volume:** {volume}%\n"
                f"⚡ **Status:** {'Enabled' if enabled else 'Disabled'}"
            )
            await interaction.followup.send(response_text)

        except Exception as e:
            logger.error(f"Error saving join sound: {e}")
            if os.path.exists(target_file_path):
                try:
                    os.remove(target_file_path)
                except Exception:
                    pass
            await interaction.followup.send(f"❌ An error occurred while saving the sound: {str(e)}")

    @app_commands.command(name="removejoinsound", description="Remove a configured voice channel join sound")
    @app_commands.describe(user="(Optional) Member whose sound to remove. Requires Manage Server if not yourself")
    async def removejoinsound(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target_user = user or interaction.user

        # Permissions check
        if target_user.id != interaction.user.id:
            perms = interaction.user.guild_permissions
            if not (perms.manage_guild or perms.administrator):
                await interaction.response.send_message(
                    "❌ You need the **Manage Server** permission to remove join sounds for other members.",
                    ephemeral=True
                )
                return

        removed = await db.remove_join_sound(interaction.guild_id, target_user.id)
        if not removed:
            msg = "ℹ️ No custom join sound is configured for you." if target_user.id == interaction.user.id else f"ℹ️ No custom join sound is configured for **{target_user.display_name}**."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Join sound removed for **{target_user.display_name}**.")

    @app_commands.command(name="myjoinsound", description="Show your currently configured join sound")
    async def myjoinsound(self, interaction: discord.Interaction):
        sound = await db.get_join_sound(interaction.guild_id, interaction.user.id)
        if not sound:
            await interaction.response.send_message("ℹ️ No custom join sound is configured for you.", ephemeral=True)
            return

        embed = discord.Embed(title="Your Custom Join Sound", color=discord.Color.blue())
        embed.add_field(name="Sound File", value=f"`{sound['sound_name']}`", inline=True)
        embed.add_field(name="Volume", value=f"{sound['volume']}%", inline=True)
        embed.add_field(name="Status", value="Enabled" if sound['enabled'] else "Disabled", inline=True)
        embed.set_footer(text="Use /setjoinsound to update or /removejoinsound to delete.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="joinsounds", description="List all configured join sounds in this server")
    async def joinsounds(self, interaction: discord.Interaction, page: int = 1):
        sounds = await db.list_guild_join_sounds(interaction.guild_id)
        if not sounds:
            await interaction.response.send_message("ℹ️ No custom join sounds have been configured for this server.", ephemeral=True)
            return

        items_per_page = 10
        total_pages = max(1, (len(sounds) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        current_slice = sounds[start_idx:end_idx]

        embed = discord.Embed(
            title=f"Configured Join Sounds for {interaction.guild.name}",
            color=discord.Color.blue()
        )

        lines = []
        for s in current_slice:
            member = interaction.guild.get_member(s['user_id'])
            user_name = member.display_name if member else f"User ID {s['user_id']}"
            status = "🟢" if s['enabled'] else "🔴"
            lines.append(f"{status} **{user_name}**: `{s['sound_name']}` (Vol: {s['volume']}%)")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Page {page}/{total_pages} • Total: {len(sounds)} configured sound(s)")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="testjoinsound", description="Test your (or another member's) join sound in your voice channel")
    @app_commands.describe(user="(Optional) Member whose sound to test. Requires Manage Server if not yourself")
    async def testjoinsound(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target_user = user or interaction.user

        # Permissions check
        if target_user.id != interaction.user.id:
            perms = interaction.user.guild_permissions
            if not (perms.manage_guild or perms.administrator):
                await interaction.response.send_message(
                    "❌ You need the **Manage Server** permission to test join sounds of other members.",
                    ephemeral=True
                )
                return

        # Check if caller is in voice
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ You must be connected to a voice channel to test a join sound.",
                ephemeral=True
            )
            return

        sound = await db.get_join_sound(interaction.guild_id, target_user.id)
        if not sound:
            msg = "ℹ️ No custom join sound is configured for you." if target_user.id == interaction.user.id else f"ℹ️ No custom join sound is configured for **{target_user.display_name}**."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if not os.path.exists(sound['sound_path']):
            await interaction.response.send_message("❌ The sound file could not be found on the server.", ephemeral=True)
            return

        state = self._get_music_state(interaction.guild_id)
        channel = interaction.user.voice.channel

        # Connect or use existing connection
        if state.voice_client is None or not state.voice_client.is_connected():
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.connect and perms.speak):
                await interaction.response.send_message("❌ Bot lacks Connect or Speak permissions in your voice channel.", ephemeral=True)
                return
            try:
                state.voice_client = await channel.connect()
                self._schedule_idle_check(interaction.guild_id, channel, delay=120)
            except Exception as e:
                await interaction.response.send_message(f"❌ Could not connect to voice channel: {e}", ephemeral=True)
                return
        elif state.voice_client.channel != channel:
            # If not playing music, move to caller channel
            if not state.mixer.has_music():
                await state.voice_client.move_to(channel)

        try:
            settings = await db.get_guild_settings(interaction.guild_id)
            state.mixer.duck_volume = float(settings.get('duck_volume', 0.25))

            ffmpeg_options = {
                'options': '-vn -filter:a "aresample=48000" -ar 48000 -ac 2'
            }
            sfx = discord.FFmpegPCMAudio(sound['sound_path'], **ffmpeg_options)
            state.mixer.add_overlay(sfx, volume=sound['volume'] / 100.0, duck_music=True)

            if not state.voice_client.is_playing():
                try:
                    state.voice_client.play(state.mixer)
                except discord.ClientException:
                    pass

            await interaction.response.send_message(f"🔊 Playing join sound for **{target_user.display_name}** (`{sound['sound_name']}`).")
        except Exception as e:
            logger.error(f"Error testing join sound: {e}")
            await interaction.response.send_message(f"❌ Error playing join sound: {e}", ephemeral=True)

    @app_commands.command(name="joinsoundconfig", description="Configure join sound settings for this server (Admin only)")
    @app_commands.describe(
        cooldown="Anti-spam cooldown between join sounds in seconds (0 to 300)",
        duck_volume="Music volume percentage while join sound plays (0% to 100%)",
        auto_connect="Whether Sargam joins your VC automatically when you join (True/False)",
        enabled="Enable or disable all custom join sounds for this server (True/False)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def joinsoundconfig(
        self,
        interaction: discord.Interaction,
        cooldown: Optional[app_commands.Range[int, 0, 300]] = None,
        duck_volume: Optional[app_commands.Range[int, 0, 100]] = None,
        auto_connect: Optional[bool] = None,
        enabled: Optional[bool] = None
    ):
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ You need the **Manage Server** permission to change server configuration.", ephemeral=True)
            return

        duck_float = (duck_volume / 100.0) if duck_volume is not None else None

        updated = await db.set_guild_settings(
            guild_id=interaction.guild_id,
            cooldown_seconds=cooldown,
            duck_volume=duck_float,
            auto_connect=auto_connect,
            enabled=enabled
        )

        embed = discord.Embed(
            title=f"Join Sound Configuration • {interaction.guild.name}",
            color=discord.Color.green()
        )
        embed.add_field(name="Master Toggle", value="Enabled" if updated['enabled'] else "Disabled", inline=True)
        embed.add_field(name="Cooldown", value=f"{updated['cooldown_seconds']}s", inline=True)
        embed.add_field(name="Music Ducking Volume", value=f"{int(updated['duck_volume'] * 100)}%", inline=True)
        embed.add_field(name="Auto-Connect to VC", value="Enabled" if updated['auto_connect'] else "Disabled", inline=True)
        embed.set_footer(text="Settings saved successfully.")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(JoinSound(bot))
