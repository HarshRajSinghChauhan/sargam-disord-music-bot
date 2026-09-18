import asyncio
import discord
import yt_dlp
import os
import json
import re
import urllib.request
import urllib.parse as urlparse

# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ''

def clean_youtube_url(url: str) -> str:
    """Strip dynamic radio/mix/user playlist parameters if a user pasted a single video URL with a Mix attached."""
    if not isinstance(url, str):
        return url
    if not ('youtube.com' in url or 'youtu.be' in url):
        return url

    try:
        parsed = urlparse.urlparse(url)
        qs = urlparse.parse_qs(parsed.query, keep_blank_values=True)
        
        video_id = qs.get('v', [None])[0]
        list_id = qs.get('list', [None])[0]
        
        # If it's a youtu.be short URL
        if not video_id and parsed.netloc in ('youtu.be', 'www.youtu.be'):
            video_id = parsed.path.lstrip('/')
            
        if video_id:
            # RD... = Radio mix, UL... = User uploads mix, LL = Liked, WL = Watch Later
            if (list_id and list_id.startswith(('RD', 'UL', 'LL', 'WL'))) or 'start_radio' in qs:
                return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        pass
    return url

def clean_search_query(query: str) -> str:
    """Clean video titles for better search matching on fallback extractors."""
    if not query:
        return ""
    # Remove bracketed/parenthesized video meta like (Official Video), [Lyrics], (Visualizer), etc.
    cleaned = re.sub(r'[\(\[][^\)\]]*(?:official|lyric|video|audio|visualizer|4k|hd|remix|version|prod|full song)[^\)\]]*[\)\]]', '', query, flags=re.IGNORECASE)
    # Remove pipes and trailing channel names (e.g., "| Lyrical BAM Hindi")
    if '|' in cleaned:
        cleaned = cleaned.split('|')[0]
    cleaned = ' '.join(cleaned.split()).strip()
    return cleaned if cleaned else query

def get_youtube_title_oembed(url: str):
    """Fetch video title and author using YouTube's lightweight oEmbed endpoint (bypasses bot checks)."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url, safe=':/?=&')}&format=json"
        req = urllib.request.Request(
            oembed_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('title'), data.get('author_name')
    except Exception as e:
        print(f"[oEmbed Warning] Could not fetch oEmbed for {url}: {e}", flush=True)
        return None, None

def format_as_netscape_cookies(content):
    if not content:
        return ""
        
    content = content.replace('\\n', '\n').strip()
    
    # 1. Already Netscape format (contains tabs or # Netscape header)
    if '# Netscape' in content or '\t' in content:
        if not content.startswith('# Netscape'):
            content = '# Netscape HTTP Cookie File\n' + content
        return content
        
    # 2. JSON format (e.g., exported from EditThisCookie / Cookie-Editor)
    if content.startswith('[') and content.endswith(']'):
        try:
            data = json.loads(content)
            lines = ['# Netscape HTTP Cookie File']
            for item in data:
                domain = item.get('domain', '.youtube.com')
                flag = 'TRUE' if domain.startswith('.') else 'FALSE'
                path = item.get('path', '/')
                secure = 'TRUE' if item.get('secure') else 'FALSE'
                expiration = str(int(item.get('expirationDate', 2147483647)))
                name = item.get('name', '')
                value = item.get('value', '')
                if name:
                    lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}")
            print(f"Parsed JSON cookies into {len(lines)-1} Netscape entries", flush=True)
            return '\n'.join(lines)
        except Exception as e:
            print(f"Error parsing JSON cookies: {e}", flush=True)

    # 3. Header format (e.g., "SID=xxx; HSID=yyy; VISITOR_INFO1_LIVE=zzz")
    lines = ['# Netscape HTTP Cookie File']
    if content.lower().startswith('cookie:'):
        content = content[7:].strip()
    
    pairs = content.split(';')
    for pair in pairs:
        if '=' in pair:
            name, value = pair.split('=', 1)
            name = name.strip()
            value = value.strip()
            if name and value:
                lines.append(f".youtube.com\tTRUE\t/\tTRUE\t2147483647\t{name}\t{value}")
                
    if len(lines) > 1:
        print(f"Parsed header cookies into {len(lines)-1} Netscape entries", flush=True)
        return '\n'.join(lines)
        
    return content

_cookies_written = False

def get_ytdl_instance(noplaylist: bool = False, use_cookies: bool = True):
    global _cookies_written
    cookies_path = 'cookies.txt'
    cookies_env = os.getenv('YOUTUBE_COOKIES')
    
    if cookies_env and not _cookies_written:
        cookies_content = format_as_netscape_cookies(cookies_env)
        try:
            with open(cookies_path, 'w', encoding='utf-8') as f:
                f.write(cookies_content)
            print(f"[YTDL] Written cookies.txt (size: {len(cookies_content)} bytes)", flush=True)
            _cookies_written = True
        except Exception as e:
            print(f"[YTDL] Error writing cookies.txt: {e}", flush=True)
            
    options = {
        'format': 'bestaudio/best/bestaudio*/best*',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': noplaylist,
        'extract_flat': 'in_playlist' if not noplaylist else False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
        'js_runtimes': {'node': {}, 'deno': {}},
        'extractor_args': {
            'youtubetab': {
                'skip': ['authcheck']
            }
        }
    }
    
    # Optional proxy to bypass datacenter IP bans (e.g. on Render / AWS)
    proxy = os.getenv('YTDL_PROXY') or os.getenv('HTTP_PROXY')
    if proxy:
        options['proxy'] = proxy
    
    if use_cookies and os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
        options['cookiefile'] = cookies_path

    return yt_dlp.YoutubeDL(options)

def get_soundcloud_ytdl_instance():
    return yt_dlp.YoutubeDL({
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'default_search': 'scsearch'
    })

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
        clean_search = clean_youtube_url(search.strip())
        is_explicit_playlist = ('playlist?list=' in clean_search) or ('list=PL' in clean_search) or ('list=OLAK' in clean_search)
        
        def _extract():
            cookies_file_exists = os.path.exists('cookies.txt') and os.path.getsize('cookies.txt') > 0
            ytdl = get_ytdl_instance(noplaylist=not is_explicit_playlist, use_cookies=True)
            try:
                return ytdl.extract_info(clean_search, download=False)
            except Exception as e:
                # If extraction with cookies failed, retry without cookies in case cookies are expired/flagged
                if cookies_file_exists and ('player response' in str(e).lower() or 'sign in' in str(e).lower() or '403' in str(e).lower()):
                    try:
                        print("[YTDL Warning] Extraction with cookies failed. Retrying without cookies...", flush=True)
                        ytdl_no_cookie = get_ytdl_instance(noplaylist=not is_explicit_playlist, use_cookies=False)
                        return ytdl_no_cookie.extract_info(clean_search, download=False)
                    except Exception as no_cookie_err:
                        e = no_cookie_err

                query = clean_search
                title_from_oembed = None
                author_from_oembed = None

                # If search is a YouTube URL, resolve title and author via oEmbed
                if ("youtube.com" in clean_search or "youtu.be" in clean_search) and clean_search.startswith(("http://", "https://")):
                    title_from_oembed, author_from_oembed = get_youtube_title_oembed(clean_search)
                    if title_from_oembed:
                        query = clean_search_query(title_from_oembed)

                print(f"[YTDL Warning] YouTube extraction failed for '{clean_search}': {e}. Trying fallback search for: '{query}'...", flush=True)
                
                # 1. First fallback: YouTube search
                if query != clean_search:
                    try:
                        yt_search_data = ytdl.extract_info(f"ytsearch1:{query}", download=False)
                        if yt_search_data and yt_search_data.get('entries'):
                            return yt_search_data
                    except Exception as yt_err:
                        print(f"[YTDL Warning] YouTube search fallback failed: {yt_err}", flush=True)

                # 2. Second fallback: SoundCloud search
                sc_ytdl = get_soundcloud_ytdl_instance()
                try:
                    sc_data = sc_ytdl.extract_info(f"scsearch:{query}", download=False)
                    if sc_data and sc_data.get('entries'):
                        return sc_data
                except Exception as sc_err:
                    print(f"[SoundCloud Warning] SoundCloud search failed: {sc_err}", flush=True)

                if title_from_oembed:
                    return {
                        'title': title_from_oembed,
                        'webpage_url': clean_search,
                        'uploader': author_from_oembed or 'YouTube',
                        'duration': 0,
                        'id': None
                    }

                return {'entries': []}

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
    async def get_stream_source(cls, track_info, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        
        webpage_url = track_info.get('webpage_url') if isinstance(track_info, dict) else track_info
        title = track_info.get('title', webpage_url) if isinstance(track_info, dict) else webpage_url
        clean_url = clean_youtube_url(webpage_url) if isinstance(webpage_url, str) else webpage_url
        
        def _extract():
            # Playing a single audio track - NEVER extract playlists or tabs
            cookies_file_exists = os.path.exists('cookies.txt') and os.path.getsize('cookies.txt') > 0
            ytdl = get_ytdl_instance(noplaylist=True, use_cookies=True)
            try:
                return ytdl.extract_info(clean_url, download=False)
            except Exception as e:
                # If extraction with cookies failed, retry without cookies
                if cookies_file_exists and ('player response' in str(e).lower() or 'sign in' in str(e).lower() or '403' in str(e).lower()):
                    try:
                        print("[YTDL Warning] Stream extraction with cookies failed. Retrying without cookies...", flush=True)
                        ytdl_no_cookie = get_ytdl_instance(noplaylist=True, use_cookies=False)
                        return ytdl_no_cookie.extract_info(clean_url, download=False)
                    except Exception as no_cookie_err:
                        e = no_cookie_err

                cleaned_title = clean_search_query(title)
                print(f"[YTDL Warning] Primary extraction failed for '{title}': {e}. Attempting search fallback with '{cleaned_title}'...", flush=True)
                
                # Try YouTube search fallback first
                if isinstance(clean_url, str) and clean_url.startswith(("http://", "https://")):
                    try:
                        yt_res = ytdl.extract_info(f"ytsearch1:{cleaned_title}", download=False)
                        if 'entries' in yt_res and yt_res['entries']:
                            return yt_res['entries'][0]
                    except Exception as yt_err:
                        print(f"[YTDL Warning] YouTube search fallback failed: {yt_err}", flush=True)

                # Fallback to SoundCloud
                sc_ytdl = get_soundcloud_ytdl_instance()
                try:
                    res = sc_ytdl.extract_info(f"scsearch:{cleaned_title}", download=False)
                    if 'entries' in res and res['entries']:
                        return res['entries'][0]
                    return res
                except Exception as sc_err:
                    print(f"[SoundCloud Warning] SoundCloud search failed: {sc_err}", flush=True)
                    return {'entries': []}

        data = await loop.run_in_executor(None, _extract)
        
        if 'entries' in data:
            if not data['entries']:
                raise Exception(f"No stream entries found for {title}")
            data = data['entries'][0]
            
        filename = data.get('url')
        if not filename:
            raise Exception(f"Could not find stream URL for {title}")
        
        headers = data.get('http_headers', {})
        user_agent = headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        dynamic_ffmpeg_options = {
            'options': '-vn -filter:a "aresample=48000" -ar 48000 -ac 2',
            'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 10M -analyzeduration 10M -user_agent "{user_agent}"'
        }
        
        return cls(discord.FFmpegPCMAudio(filename, **dynamic_ffmpeg_options), data=data)
