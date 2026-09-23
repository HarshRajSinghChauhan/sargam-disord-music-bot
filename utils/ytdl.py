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
                
import asyncio
import discord
import yt_dlp
import os
import json
import re
import urllib.request
import urllib.parse as urlparse
from utils.saavn import search_saavn

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

META_NOISE_WORDS = {
    'official', 'video', 'song', 'songs', 'audio', 'track', 'tracks', 'music',
    'lyric', 'lyrics', 'lyrical', 'full', 'hd', '4k', '1080p', '720p',
    'remastered', 'version', 'remix', 'mix', 'prod', 'original', 'soundtrack',
    'love', 'romantic', 'sad', 'status', 'special', 'latest', 'new', 'hit', 'hits'
}

def is_noise_segment(seg: str) -> bool:
    cleaned = re.sub(r'\b(19|20)\d{2}\b', '', seg)
    words = [w.lower() for w in re.findall(r'\w+', cleaned)]
    if not words:
        return True
    return all(w in META_NOISE_WORDS for w in words)

def clean_youtube_query(raw_title: str, channel_author: str = '') -> str:
    """Extract a clean, high-precision search query from a messy YouTube title."""
    if not raw_title:
        return ''
    t = raw_title.strip()
    
    # 1. Strip bracketed noise first: (Official Video), [Lyrics], etc.
    t = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', t)
    
    # 2. Check for quoted song name like "Beete Lamhe"
    quoted = re.findall(r'[\"“\']([^\"“\']+)[\"”\']', t)
    
    # 3. Strip noise words
    noise_regex = r'\b(?:lyrical\s+video\s+song|lyrical\s+video|lyric\s+video|lyrical|lyrics|official\s+music\s+video|official\s+video\s+song|official\s+video|official\s+audio|music\s+video|video\s+song|full\s+video\s+song|full\s+video|full\s+song|full\s+audio|audio\s+song|audio\s+track|4k\s+ultra\s+hd|4k\s+hd|ultra\s+hd|1080p|remastered|video|audio|song)\b'
    t = re.sub(noise_regex, ' ', t, flags=re.IGNORECASE)
    
    # 4. Strip channel branding like | T-Series ...
    t = re.sub(r'\|\s*(?:t-series|zee\s+music|sony\s+music|yrf|tips|saregama|speed\s+records)[^|]*$', '', t, flags=re.IGNORECASE)
    
    # 5. Split segments by pipe or hyphen
    segments = [s.strip() for s in re.split(r'\s*[\u2013\u2014|]\s*', t) if s.strip()]
    
    song_name = quoted[0].strip() if quoted and len(quoted[0].strip()) > 2 else (segments[0] if segments else t)
    song_name = re.sub(r'[\"“”\']', '', song_name).strip()
    
    # Collect key context: up to 2 extra non-noise segments (artist, movie name)
    context_words = []
    if len(segments) > 1:
        for s in segments[1:]:
            cleaned_s = re.sub(r'[\"“”\']', '', s).strip()
            if len(cleaned_s) > 1 and not is_noise_segment(cleaned_s) and len(cleaned_s.split()) <= 4:
                context_words.append(cleaned_s)
                if len(context_words) >= 2:
                    break
                
    if context_words:
        query = f"{song_name} {' '.join(context_words)}"
    else:
        query = song_name
        
    return ' '.join(query.split()).strip()

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

def ensure_cookies_written():
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

# Write cookies immediately on startup if available
ensure_cookies_written()

def get_ytdl_instance(noplaylist: bool = False, use_cookies: bool = True, use_proxy: bool = False, player_clients: list = None):
    ensure_cookies_written()
    cookies_path = 'cookies.txt'
    
    # Default to android/ios mobile clients which bypass YouTube's datacenter IP bot detection
    clients = player_clients or ['android', 'ios']
    
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
        'source_address': '0.0.0.0',
        'socket_timeout': 5,  # Fast 5s timeout to prevent hanging on dead connections
        'retries': 0,
        'fragment_retries': 0,
        'js_runtimes': {'node': {}, 'deno': {}},
        'extractor_args': {
            'youtubetab': {
                'skip': ['authcheck']
            },
            'youtube': {
                'player_client': clients
            }
        }
    }
    
    # Optional proxy support only when explicitly requested
    if use_proxy:
        proxy_env = os.getenv('YTDL_PROXY') or os.getenv('HTTP_PROXY')
        if proxy_env:
            proxies = [p.strip() for p in proxy_env.split(',') if p.strip()]
            if proxies:
                import random
                selected_proxy = random.choice(proxies)
                options['proxy'] = selected_proxy
    
    if use_cookies and os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
        options['cookiefile'] = cookies_path

    return yt_dlp.YoutubeDL(options)

def extract_youtube_info(target: str, noplaylist: bool = False):
    ensure_cookies_written()
    cookies_available = os.path.exists('cookies.txt') and os.path.getsize('cookies.txt') > 0

    # Keep attempts fast and direct (max 2 attempts, 5s timeout each)
    attempts = []
    if cookies_available:
        attempts.append({'use_cookies': True, 'use_proxy': False, 'clients': ['android', 'ios'], 'desc': 'android client with cookies'})
    attempts.append({'use_cookies': False, 'use_proxy': False, 'clients': ['android', 'ios'], 'desc': 'android client direct IP'})

    last_err = None
    for attempt in attempts:
        try:
            ydl = get_ytdl_instance(
                noplaylist=noplaylist,
                use_cookies=attempt['use_cookies'],
                use_proxy=attempt.get('use_proxy', False),
                player_clients=attempt.get('clients')
            )
            data = ydl.extract_info(target, download=False)
            if data:
                return data
        except Exception as err:
            last_err = err
            print(f"[YTDL] Attempt '{attempt['desc']}' failed for '{target}': {err}", flush=True)

    raise last_err or Exception(f"Failed to extract YouTube info for {target}")


def get_soundcloud_ytdl_instance():
    return yt_dlp.YoutubeDL({
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'socket_timeout': 5,
        'retries': 0,
        'default_search': 'scsearch'
    })

def is_valid_soundcloud_entry(entry, original_query: str = ""):
    if not isinstance(entry, dict):
        return False
    url = str(entry.get('url', '')).lower()
    if not url or 'cf-preview-media' in url or '/preview/' in url:
        return False
    duration = entry.get('duration')
    if duration is not None and duration <= 30:
        return False

    title = str(entry.get('title', '')).lower()
    orig_q = (original_query or "").lower()

    # Filter out common modified/amateur tracks (slowed, reverb, raw acoustic cover)
    # unless the user specifically searched for those terms
    unwanted_keywords = ['slowed', 'reverb', 'slow+reverb', 'slowed+reverb', 'acoustic cover', 'guitar cover', 'unplugged cover', 'raw']
    for kw in unwanted_keywords:
        if kw in title and kw not in orig_q:
            return False

    return True


ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url') # Stream URL or original URL
        self.webpage_url = data.get('webpage_url')
        self.uploader = data.get('uploader')
        self.duration = data.get('duration')

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        clean_search = clean_youtube_url(search.strip())
        is_url = clean_search.startswith(("http://", "https://"))
        is_explicit_playlist = is_url and (('playlist?list=' in clean_search) or ('list=PL' in clean_search) or ('list=OLAK' in clean_search))
        
        def _extract():
            # 1. Fast path for text search: check JioSaavn FIRST (instant 0.5s response, 320kbps CD master)
            if not is_url:
                saavn_track = search_saavn(clean_search)
                if saavn_track:
                    return {'entries': [saavn_track]}

            # 2. Fast path for YouTube URL: resolve title via oEmbed and check JioSaavn FIRST with strict matching!
            title_from_oembed = None
            author_from_oembed = None
            if is_url and ("youtube.com" in clean_search or "youtu.be" in clean_search) and not is_explicit_playlist:
                title_from_oembed, author_from_oembed = get_youtube_title_oembed(clean_search)
                if title_from_oembed:
                    smart_query = clean_youtube_query(title_from_oembed, author_from_oembed)
                    saavn_track = search_saavn(smart_query)
                    if saavn_track:
                        return {'entries': [saavn_track]}

            # 3. Direct YouTube extraction (for explicit playlists, or if not found on JioSaavn)
            if is_url:
                try:
                    return extract_youtube_info(clean_search, noplaylist=not is_explicit_playlist)
                except Exception as e:
                    print(f"[YTDL Warning] Direct YouTube extraction failed for '{clean_search}': {e}. Trying fallbacks...", flush=True)
                    if not title_from_oembed and ("youtube.com" in clean_search or "youtu.be" in clean_search):
                        title_from_oembed, author_from_oembed = get_youtube_title_oembed(clean_search)

            # 4. Fallback / search resolution path
            if title_from_oembed:
                query = clean_youtube_query(title_from_oembed, author_from_oembed)
            else:
                query = clean_youtube_query(clean_search)

            # Check JioSaavn if not checked earlier
            saavn_track = search_saavn(query)
            if saavn_track:
                return {'entries': [saavn_track]}

            # YouTube search fallback
            try:
                yt_search_data = extract_youtube_info(f"ytsearch1:{query}", noplaylist=True)
                if yt_search_data and yt_search_data.get('entries'):
                    return yt_search_data
            except Exception as yt_err:
                print(f"[YTDL Warning] YouTube search fallback failed: {yt_err}", flush=True)

            # SoundCloud search fallback
            sc_ytdl = get_soundcloud_ytdl_instance()
            try:
                sc_data = sc_ytdl.extract_info(f"scsearch5:{query}", download=False)
                if sc_data and sc_data.get('entries'):
                    valid_entries = [e for e in sc_data['entries'] if is_valid_soundcloud_entry(e, query)]
                    if valid_entries:
                        sc_data['entries'] = valid_entries
                        return sc_data
            except Exception as sc_err:
                print(f"[SoundCloud Warning] SoundCloud search failed: {sc_err}", flush=True)

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
            'duration': int(round(float(data['duration']))) if data.get('duration') is not None else None,
            'id': data.get('id'),
            'url': data.get('url'),
            'extractor': data.get('extractor'),
            'http_headers': data.get('http_headers')
        }

    @classmethod
    async def get_stream_source(cls, track_info, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        
        # 1. INSTANT: If track is already from JioSaavn or has pre-resolved audio URL, start playing with 0ms delay!
        if isinstance(track_info, dict) and track_info.get('extractor') == 'jiosaavn' and track_info.get('url'):
            filename = track_info['url']
            headers = track_info.get('http_headers', {})
            user_agent = headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            dynamic_ffmpeg_options = {
                'options': '-vn',
                'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 10M -analyzeduration 10M -user_agent "{user_agent}"'
            }
            return cls(discord.FFmpegPCMAudio(filename, **dynamic_ffmpeg_options), data=track_info)

        webpage_url = track_info.get('webpage_url') if isinstance(track_info, dict) else track_info
        title = track_info.get('title', webpage_url) if isinstance(track_info, dict) else webpage_url
        clean_url = clean_youtube_url(webpage_url) if isinstance(webpage_url, str) else webpage_url
        
        def _extract():
            # If the URL is already a direct SoundCloud URL
            if isinstance(clean_url, str) and 'soundcloud.com' in clean_url:
                sc_ytdl = get_soundcloud_ytdl_instance()
                try:
                    res = sc_ytdl.extract_info(clean_url, download=False)
                    if res and is_valid_soundcloud_entry(res, title):
                        return res
                    if res and res.get('url'):
                        return res
                except Exception as sc_url_err:
                    print(f"[SoundCloud Warning] Direct SoundCloud extraction failed: {sc_url_err}", flush=True)

            # If it's a YouTube URL, extract audio from that exact video first!
            if isinstance(clean_url, str) and ('youtube.com' in clean_url or 'youtu.be' in clean_url):
                try:
                    return extract_youtube_info(clean_url, noplaylist=True)
                except Exception as e:
                    print(f"[YTDL Warning] Direct YouTube stream extraction failed for '{title}': {e}. Trying fallbacks...", flush=True)

            cleaned_title = clean_youtube_query(title)

            # Fallback 1: Check JioSaavn with strict matching
            saavn_track = search_saavn(cleaned_title)
            if saavn_track:
                return saavn_track

            # Fallback 2: Quick YouTube search fallback
            try:
                yt_res = extract_youtube_info(f"ytsearch1:{cleaned_title}", noplaylist=True)
                if 'entries' in yt_res and yt_res['entries']:
                    return yt_res['entries'][0]
            except Exception as yt_err:
                print(f"[YTDL Warning] YouTube search fallback failed: {yt_err}", flush=True)

            # Fallback 3: Fallback to SoundCloud
            sc_ytdl = get_soundcloud_ytdl_instance()
            try:
                res = sc_ytdl.extract_info(f"scsearch5:{cleaned_title}", download=False)
                if res and 'entries' in res and res['entries']:
                    valid_entries = [e for e in res['entries'] if is_valid_soundcloud_entry(e, cleaned_title)]
                    if valid_entries:
                        return valid_entries[0]
                if res and is_valid_soundcloud_entry(res, cleaned_title):
                    return res
            except Exception as sc_err:
                print(f"[SoundCloud Warning] SoundCloud search failed: {sc_err}", flush=True)
                return {'entries': []}

        data = await loop.run_in_executor(None, _extract)
        
        if not data:
            raise Exception(f"No playable stream found for {title}")

        if isinstance(data, dict) and 'entries' in data:
            if not data['entries']:
                raise Exception(f"No stream entries found for {title}")
            data = data['entries'][0]
            
        filename = data.get('url')
        if not filename:
            raise Exception(f"Could not find stream URL for {title}")
        
        headers = data.get('http_headers', {})
        user_agent = headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        dynamic_ffmpeg_options = {
            'options': '-vn',
            'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 10M -analyzeduration 10M -user_agent "{user_agent}"'
        }
        
        return cls(discord.FFmpegPCMAudio(filename, **dynamic_ffmpeg_options), data=data)
