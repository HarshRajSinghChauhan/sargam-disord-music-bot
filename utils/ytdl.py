import asyncio
import discord
import yt_dlp
import os

# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ''

def get_ytdl_instance():
    cookies_path = 'cookies.txt'
    cookies_env = os.getenv('YOUTUBE_COOKIES')
    
    if cookies_env:
        # Handle literal \n if Render escaped multiline env variable
        cookies_content = cookies_env.replace('\\n', '\n').strip()
        if not cookies_content.startswith('# Netscape'):
            cookies_content = '# Netscape HTTP Cookie File\n' + cookies_content
            
        with open(cookies_path, 'w', encoding='utf-8') as f:
            f.write(cookies_content)
            
    options = {
        'format': 'bestaudio/best/bestaudio*/best*',
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
                'player_client': ['web', 'mweb', 'ios', 'android']
            }
        }
    }
    
    if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
        options['cookiefile'] = cookies_path
        print("Using cookies.txt for yt-dlp extraction")

    return yt_dlp.YoutubeDL(options)

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

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
        
        def _extract():
            ytdl = get_ytdl_instance()
            return ytdl.extract_info(search, download=False)

        data = await loop.run_in_executor(None, _extract)
        
        if 'entries' in data:
            # It's a playlist or search result
            return [cls.process_entry(entry) for entry in data['entries'] if entry]
        else:
            # Single video
            return [cls.process_entry(data)]

    @classmethod
    def process_entry(cls, data):
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
        
        def _extract():
            ytdl = get_ytdl_instance()
            return ytdl.extract_info(webpage_url, download=False)

        data = await loop.run_in_executor(None, _extract)
        
        if 'entries' in data:
            data = data['entries'][0]
            
        filename = data['url']
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
