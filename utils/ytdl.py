import asyncio
import discord
import yt_dlp

# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ''

import os

# Check for cookies file or environment variable
cookies_path = 'cookies.txt'
if os.getenv('YOUTUBE_COOKIES'):
    with open('cookies.txt', 'w', encoding='utf-8') as f:
        f.write(os.getenv('YOUTUBE_COOKIES'))

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False, # We want to handle playlists
    'extract_flat': 'in_playlist', # For playlists, extract info quickly without downloading
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android_vr', 'tvhtml5', 'web_creator', 'mweb']
        }
    }
}

if os.path.exists(cookies_path):
    ytdl_format_options['cookiefile'] = cookies_path

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url') # This might be the stream URL or original URL
        self.webpage_url = data.get('webpage_url')
        self.uploader = data.get('uploader')
        self.duration = data.get('duration')

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        
        # Determine if it's a playlist or a direct video search
        # To avoid downloading everything, we extract info
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        
        if 'entries' in data:
            # It's a playlist or search result
            # Return the list of entries (basic metadata)
            return [cls.process_entry(entry) for entry in data['entries'] if entry]
        else:
            # Single video
            return [cls.process_entry(data)]

    @classmethod
    def process_entry(cls, data):
        # We don't create the FFmpegPCMAudio here because stream URLs expire.
        # We just return the metadata, and we'll extract the stream URL right before playing.
        return {
            'title': data.get('title'),
            'webpage_url': data.get('webpage_url') or data.get('url'),
            'uploader': data.get('uploader'),
            'duration': data.get('duration'),
            'id': data.get('id')
        }

    @classmethod
    async def get_stream_source(cls, webpage_url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        # Extract again just before playing to get a fresh stream URL
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(webpage_url, download=False))
        
        if 'entries' in data:
            # Take first item if it somehow resolved to a playlist
            data = data['entries'][0]
            
        filename = data['url']
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
