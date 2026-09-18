# Discord Music Bot

A production-ready Discord music bot that supports playing audio from YouTube videos and playlists using `yt-dlp` and `FFmpeg`.

## Features
- Plays YouTube videos and playlists.
- Per-server isolated queue management.
- Discord Slash Commands (`/play`, `/pause`, `/skip`, `/queue`, etc.).
- Efficient audio extraction (no downloading entire videos unless necessary, fresh stream URL resolution to avoid timeouts).
- Built with Python 3.11, `discord.py` 2.4.0, and Docker.

## Setup Instructions

### 1. Discord Developer Portal Setup
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a new Application and add a Bot.
3. Under the Bot tab, enable the **Message Content Intent** and **Server Members Intent**.
4. Copy the Bot Token.
5. Under OAuth2 -> URL Generator, select `bot` and `applications.commands` scopes.
6. Select permissions: Send Messages, Embed Links, Connect, Speak, Use Voice Activity.
7. Use the generated URL to invite the bot to your server.

### 2. Configuration
1. Rename `.example.env` to `.env`.
2. Open `.env` and fill in your values:
   - `DISCORD_TOKEN`: The bot token you copied earlier.
   - `TEST_GUILD_ID`: (Optional) The ID of your test server. Adding this syncs slash commands instantly to that server during development. If left empty, global commands are used (which can take an hour to appear in Discord).

### 3. Deployment with Docker (Recommended)
Make sure you have Docker and Docker Compose installed.

Run the bot in the background:
```bash
docker-compose up --build -d
```

To view logs:
```bash
docker-compose logs -f
```

To stop the bot:
```bash
docker-compose down
```

## Slash Commands
- `/play [url or search]`: Play a song or playlist.
- `/pause`: Pause the current song.
- `/resume`: Resume playback.
- `/skip`: Skip the current song.
- `/stop`: Stop playing and clear the queue.
- `/queue [page]`: View the current queue.
- `/nowplaying`: View details of the currently playing track.
- `/remove [index]`: Remove a specific track from the queue.
- `/clear`: Clear the queue.
- `/shuffle`: Shuffle the queue.
- `/volume [0-100]`: Adjust the bot's volume.
- `/loop`: Toggle looping for the current track.

### Custom Join Sound Commands
- `/setjoinsound [sound] [user] [volume] [enabled]`: Assign a custom sound (MP3/WAV/OGG, max 10s) to play when you (or another member, if admin) join a voice channel.
- `/removejoinsound [user]`: Remove the assigned join sound.
- `/myjoinsound`: View your currently assigned join sound details.
- `/joinsounds [page]`: View all configured join sounds in this server.
- `/testjoinsound [user]`: Test and preview your join sound in your current voice channel.
- `/joinsoundconfig [cooldown] [duck_volume] [auto_connect] [enabled]`: (Admin only) Configure server-specific join sound settings, anti-spam cooldown, and music ducking volume.
