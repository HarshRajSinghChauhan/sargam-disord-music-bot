import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from utils.ytdl import YTDLSource
import math

class GuildState:
    def __init__(self):
        self.queue = []
        self.current = None
        self.voice_client = None
        self.loop = False
        self.play_next_event = asyncio.Event()
        self.player_task = None
        self.volume = 0.5

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.states = {}

    def get_state(self, guild_id):
        if guild_id not in self.states:
            self.states[guild_id] = GuildState()
        return self.states[guild_id]

    def cog_unload(self):
        for state in self.states.values():
            if state.player_task:
                state.player_task.cancel()

    async def player_loop(self, guild_id, state):
        while True:
            state.play_next_event.clear()

            if not state.loop or state.current is None:
                if len(state.queue) == 0:
                    # Queue is empty, wait for a bit before disconnecting
                    await asyncio.sleep(300) # 5 minutes idle
                    if len(state.queue) == 0 and state.voice_client and state.voice_client.is_connected():
                        await state.voice_client.disconnect()
                        del self.states[guild_id]
                    return
                state.current = state.queue.pop(0)

            try:
                # Get fresh stream URL right before playing
                source = await YTDLSource.get_stream_source(state.current['webpage_url'], loop=self.bot.loop)
                source.volume = state.volume
            except Exception as e:
                print(f"Error extracting stream for {state.current['title']}: {e}")
                # Skip to next track
                state.current = None
                continue

            state.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(state.play_next_event.set))
            
            await state.play_next_event.wait()
            
            if not state.loop:
                state.current = None

    async def _send(self, interaction: discord.Interaction, content: str, ephemeral: bool = True):
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)

    async def _join(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not interaction.user.voice:
            await self._send(interaction, "You are not connected to a voice channel.", ephemeral=True)
            return False

        channel = interaction.user.voice.channel
        if state.voice_client is None or not state.voice_client.is_connected():
            try:
                state.voice_client = await channel.connect()
            except asyncio.TimeoutError:
                await self._send(interaction, "Could not connect to the voice channel.", ephemeral=True)
                return False
        elif state.voice_client.channel != channel:
            await state.voice_client.move_to(channel)
        
        return True

    @app_commands.command(name="play", description="Play a song or playlist from YouTube")
    async def play(self, interaction: discord.Interaction, search: str):
        await interaction.response.defer()
        
        if not await self._join(interaction):
            return

        state = self.get_state(interaction.guild_id)

        try:
            entries = await YTDLSource.create_source(interaction, search, loop=self.bot.loop)
        except Exception as e:
            await interaction.followup.send(f"An error occurred while processing the request: {str(e)}")
            return

        if not entries:
            await interaction.followup.send("Could not find any songs.")
            return

        added = len(entries)
        state.queue.extend(entries)

        if added == 1:
            await interaction.followup.send(f"Added to queue: **{entries[0]['title']}**")
        else:
            await interaction.followup.send(f"Added {added} songs to the queue from playlist.")

        if state.player_task is None or state.player_task.done():
            state.player_task = self.bot.loop.create_task(self.player_loop(interaction.guild_id, state))

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()
            # If looping is enabled, we should probably break the loop on manual skip
            state.loop = False 
            await interaction.response.send_message("Skipped the current song.")
        else:
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            await interaction.response.send_message("Paused playback.")
        else:
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume the paused song")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            await interaction.response.send_message("Resumed playback.")
        else:
            await interaction.response.send_message("Audio is not paused.", ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and clear the queue")
    async def stop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        state.loop = False
        if state.voice_client:
            state.voice_client.stop()
            await state.voice_client.disconnect()
            state.voice_client = None
            if interaction.guild_id in self.states:
                del self.states[interaction.guild_id]
            await interaction.response.send_message("Stopped playback and cleared the queue.")
        else:
            await interaction.response.send_message("Bot is not in a voice channel.", ephemeral=True)

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction, page: int = 1):
        state = self.get_state(interaction.guild_id)
        if not state.queue and not state.current:
            await interaction.response.send_message("The queue is currently empty.")
            return

        items_per_page = 10
        pages = math.ceil(len(state.queue) / items_per_page)
        page = max(1, min(page, pages if pages > 0 else 1))

        start = (page - 1) * items_per_page
        end = start + items_per_page
        queue_slice = state.queue[start:end]

        embed = discord.Embed(title=f"Queue for {interaction.guild.name}", color=discord.Color.blue())
        
        if state.current:
            embed.add_field(name="Now Playing", value=f"**{state.current['title']}**", inline=False)
            
        if queue_slice:
            queue_text = ""
            for i, track in enumerate(queue_slice, start=start+1):
                queue_text += f"`{i}.` {track['title']}\n"
            embed.add_field(name=f"Up Next (Page {page}/{pages if pages > 0 else 1})", value=queue_text, inline=False)
            
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Show currently playing song")
    async def nowplaying(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.current:
            embed = discord.Embed(title="Now Playing", description=f"[{state.current['title']}]({state.current['webpage_url']})", color=discord.Color.green())
            if state.current.get('uploader'):
                embed.add_field(name="Channel", value=state.current['uploader'])
            if state.current.get('duration'):
                mins, secs = divmod(state.current['duration'], 60)
                embed.add_field(name="Duration", value=f"{mins}:{secs:02d}")
            embed.set_footer(text=f"Loop: {'Enabled' if state.loop else 'Disabled'}")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Nothing is currently playing.")

    @app_commands.command(name="remove", description="Remove a song from the queue by index")
    async def remove(self, interaction: discord.Interaction, index: int):
        state = self.get_state(interaction.guild_id)
        if 1 <= index <= len(state.queue):
            removed = state.queue.pop(index - 1)
            await interaction.response.send_message(f"Removed **{removed['title']}** from the queue.")
        else:
            await interaction.response.send_message("Invalid index.", ephemeral=True)

    @app_commands.command(name="clear", description="Clear the entire queue")
    async def clear(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        await interaction.response.send_message("Queue has been cleared.")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        import random
        random.shuffle(state.queue)
        await interaction.response.send_message("Queue has been shuffled.")

    @app_commands.command(name="volume", description="Set the volume (0-100)")
    async def volume(self, interaction: discord.Interaction, level: int):
        state = self.get_state(interaction.guild_id)
        level = max(0, min(level, 100))
        state.volume = level / 100.0
        
        if state.voice_client and state.voice_client.source:
            state.voice_client.source.volume = state.volume
            
        await interaction.response.send_message(f"Volume set to {level}%")

    @app_commands.command(name="loop", description="Toggle looping for the current song")
    async def loop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        state.loop = not state.loop
        status = "enabled" if state.loop else "disabled"
        await interaction.response.send_message(f"Looping is now {status}.")

async def setup(bot):
    await bot.add_cog(Music(bot))
