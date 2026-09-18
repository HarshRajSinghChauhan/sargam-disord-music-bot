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

def get_ytdl_instance(noplaylist: bool = False, use_cookies: bool = True, use_proxy: bool = True, player_clients: list = None):
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
    
    # Optional proxy support (supports single proxy or comma-separated list for auto-rotation)
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
    proxy_available = bool(os.getenv('YTDL_PROXY') or os.getenv('HTTP_PROXY'))

    attempts = []
    # Primary attempts using Android/iOS clients (effective on datacenter IPs like Render)
    if cookies_available:
        if proxy_available:
            attempts.append({'use_cookies': True, 'use_proxy': True, 'clients': ['android', 'ios'], 'desc': 'android client with cookies & proxy'})
        attempts.append({'use_cookies': True, 'use_proxy': False, 'clients': ['android', 'ios'], 'desc': 'android client with cookies direct IP'})
    if proxy_available:
        attempts.append({'use_cookies': False, 'use_proxy': True, 'clients': ['android', 'ios'], 'desc': 'android client without cookies & proxy'})
    attempts.append({'use_cookies': False, 'use_proxy': False, 'clients': ['android', 'ios'], 'desc': 'android client without cookies direct IP'})

    # Fallback clients
    attempts.append({'use_cookies': False, 'use_proxy': False, 'clients': ['tv_embedded', 'android_creator'], 'desc': 'tv_embedded/android_creator fallback'})
    attempts.append({'use_cookies': False, 'use_proxy': False, 'clients': None, 'desc': 'default yt-dlp clients'})

    last_err = None
    for attempt in attempts:
        try:
            ydl = get_ytdl_instance(
                noplaylist=noplaylist,
                use_cookies=attempt['use_cookies'],
                use_proxy=attempt['use_proxy'],
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
        is_explicit_playlist = ('playlist?list=' in clean_search) or ('list=PL' in clean_search) or ('list=OLAK' in clean_search)
        
        def _extract():
            try:
                return extract_youtube_info(clean_search, noplaylist=not is_explicit_playlist)
            except Exception as e:
                query = clean_search
                title_from_oembed = None
                author_from_oembed = None

                # If search is a YouTube URL, resolve title and author via oEmbed
                if ("youtube.com" in clean_search or "youtu.be" in clean_search) and clean_search.startswith(("http://", "https://")):
                    title_from_oembed, author_from_oembed = get_youtube_title_oembed(clean_search)
                    if title_from_oembed:
                        query = clean_search_query(title_from_oembed)

                print(f"[YTDL Warning] Direct YouTube extraction failed for '{clean_search}': {e}. Trying YouTube search for: '{query}'...", flush=True)

                # 1. First fallback: YouTube search (using Android mobile client)
                try:
                    yt_search_data = extract_youtube_info(f"ytsearch1:{query}", noplaylist=True)
                    if yt_search_data and yt_search_data.get('entries'):
                        return yt_search_data
                except Exception as yt_err:
                    print(f"[YTDL Warning] YouTube search fallback failed: {yt_err}", flush=True)

                # 2. Second fallback: JioSaavn (320kbps official studio audio - immune to datacenter blocks)
                saavn_track = search_saavn(query)
                if saavn_track:
                    return {'entries': [saavn_track]}

                # 3. Third fallback: SoundCloud search (strict filter to prevent slowed/covers)
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
            'id': data.get('id'),
            'url': data.get('url'),
            'extractor': data.get('extractor')
        }

    @classmethod
    async def get_stream_source(cls, track_info, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        
        webpage_url = track_info.get('webpage_url') if isinstance(track_info, dict) else track_info
        title = track_info.get('title', webpage_url) if isinstance(track_info, dict) else webpage_url
        clean_url = clean_youtube_url(webpage_url) if isinstance(webpage_url, str) else webpage_url
        
        def _extract():
            # If the URL is already a direct SoundCloud URL, use the SoundCloud extractor directly
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

            # If track is from JioSaavn or already has a direct audio stream URL, return it directly
            if isinstance(track_info, dict) and track_info.get('extractor') == 'jiosaavn' and track_info.get('url'):
                return track_info

            try:
                return extract_youtube_info(clean_url, noplaylist=True)
            except Exception as e:
                cleaned_title = clean_search_query(title)
                print(f"[YTDL Warning] Primary extraction failed for '{title}': {e}. Attempting fallback with '{cleaned_title}'...", flush=True)

                # 1. Try YouTube search fallback (with Android mobile client)
                try:
                    yt_res = extract_youtube_info(f"ytsearch1:{cleaned_title}", noplaylist=True)
                    if 'entries' in yt_res and yt_res['entries']:
                        return yt_res['entries'][0]
                except Exception as yt_err:
                    print(f"[YTDL Warning] YouTube search fallback failed: {yt_err}", flush=True)

                # 2. Try JioSaavn fallback (320kbps official studio audio - immune to datacenter blocks)
                saavn_track = search_saavn(cleaned_title)
                if saavn_track:
                    return saavn_track

                # 3. Fallback to SoundCloud (strict filter against slowed/covers)
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
            'options': '-vn',
            'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 10M -analyzeduration 10M -user_agent "{user_agent}"'
        }
        
        return cls(discord.FFmpegPCMAudio(filename, **dynamic_ffmpeg_options), data=data)
