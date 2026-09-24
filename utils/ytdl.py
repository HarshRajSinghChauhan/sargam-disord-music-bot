import asyncio
import discord
import yt_dlp
import os
import random
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
            # Only strip radio mixes (RD/UL/LL/WL, start_radio) - preserve all actual user playlists (PL...)
            if (list_id and list_id.startswith(('RD', 'UL', 'LL', 'WL'))) or 'start_radio' in qs:
                return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        pass
    return url

META_NOISE_WORDS = {
    'official', 'video', 'song', 'songs', 'audio', 'track', 'tracks', 'music',
    'lyric', 'lyrics', 'lyrical', 'lyrcial', 'full', 'hd', '4k', '1080p', '720p',
    'remastered', 'version', 'remix', 'mix', 'prod', 'original', 'soundtrack',
    'love', 'romantic', 'sad', 'status', 'special', 'latest', 'new', 'hit', 'hits',
    'best', 'top', 'popular', 'trending', 'all', 'with', 'r&b', 'late', 'night', 'virul',
    'musicvideo', 'dance', 'feat', 'ft'
}

def is_noise_segment(seg: str) -> bool:
    cleaned = re.sub(r'\b(19|20)\d{2}\b', '', seg)
    cleaned = re.sub(r'#\w+', '', cleaned)
    words = [w.lower() for w in re.findall(r'\w+', cleaned)]
    if not words:
        return True
    return all(w in META_NOISE_WORDS for w in words)

LABEL_KEYWORDS = {
    'series', 'music', 'records', 'studio', 'studios', 'entertainment', 'films', 'media',
    'vevo', 'audio', 'channel', 'company', 'production', 'productions', 'official', 'zee', 'tseries'
}

def extract_expected_artist(raw_title: str, channel_author: str = '') -> str:
    """Extract likely artist name from YouTube title segments or channel author."""
    if channel_author:
        author_lower = channel_author.lower()
        if not any(kw in author_lower for kw in LABEL_KEYWORDS):
            return channel_author

    raw_segs = [s.strip() for s in re.split(r'\s*[\u2013\u2014|\-]\s*', raw_title or '') if s.strip()]
    segs = [s for s in raw_segs if not is_noise_segment(s)]
    if len(segs) >= 2:
        s1_lower = segs[1].lower()
        if not any(kw in s1_lower for kw in LABEL_KEYWORDS):
            return segs[1]
        s0_lower = segs[0].lower()
        if not any(kw in s0_lower for kw in LABEL_KEYWORDS):
            return segs[0]

    return channel_author or ''

def get_search_candidates(raw_title: str, channel_author: str = '') -> list:
    """Generate prioritized search query candidates from a messy YouTube title."""
    if not raw_title:
        return []

    t = raw_title.strip()
    # Strip emojis and symbols
    t = re.sub(r'[\U00010000-\U0010ffff]', ' ', t)
    # Check for quoted song name like "Beete Lamhe"
    quoted = re.findall(r'[\"“\']([^\"“\']+)[\"”\']', t)

    # Strip bracketed noise: (Official Video), [Lyrics], etc.
    t = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', t)

    # Strip noise words
    noise_regex = r'\b(?:lyrical\s+video\s+song|lyrical\s+video|lyric\s+video|lyrcial\s+video|lyrcial|lyrical|lyrics|official\s+music\s+video|official\s+video\s+song|official\s+video|official\s+audio|music\s+video|video\s+song|full\s+video\s+song|full\s+video|full\s+song|full\s+audio|audio\s+song|audio\s+track|4k\s+ultra\s+hd|4k\s+hd|ultra\s+hd|1080p|remastered|video|audio|song|with\s+lyrics)\b'
    t = re.sub(noise_regex, ' ', t, flags=re.IGNORECASE)

    # Strip channel branding like | T-Series ...
    t = re.sub(r'\|\s*(?:t-series|zee\s+music|sony\s+music|yrf|tips|saregama|speed\s+records|coke\s+studio\s+bharat|coke\s+studio\s+india|play\s+dmf)[^|]*$', '', t, flags=re.IGNORECASE)

    # Split segments by pipe, hyphen, en-dash, or em-dash
    raw_segs = [s.strip() for s in re.split(r'\s*[\u2013\u2014|\-]\s*', t) if s.strip()]
    segs = []
    for s in raw_segs:
        # Strip trailing ft. / feat. info like 'ft. Sana Khan'
        s_clean = re.sub(r'\b(?:ft\.?|feat\.?)\s+.*$', '', s, flags=re.IGNORECASE).strip()
        if s_clean and not is_noise_segment(s_clean):
            segs.append(s_clean)
        elif not is_noise_segment(s):
            segs.append(s)

    valid_segs = [s for s in segs if not is_noise_segment(s)]

    candidates = []

    # Candidate 1: Quoted text (highest priority)
    if quoted:
        q_clean = re.sub(noise_regex, ' ', quoted[0], flags=re.IGNORECASE).strip()
        q_clean = re.sub(r'[\"“”\']', '', q_clean).strip()
        if len(q_clean) > 2 and not is_noise_segment(q_clean):
            candidates.append(q_clean)
            if len(valid_segs) > 1:
                candidates.append(f"{q_clean} {valid_segs[1]}")

    # Candidate 2: First two valid segments (e.g. "Ye Baarish Darshan Raval", "Gajendra Verma Tera Hi Rahun")
    if len(valid_segs) >= 2:
        candidates.append(f"{valid_segs[0]} {valid_segs[1]}")
        candidates.append(f"{valid_segs[1]} {valid_segs[0]}")
    elif valid_segs:
        # Candidate 3: Single segment ONLY if no other segment exists (never drop artist if available)
        candidates.append(valid_segs[0])

    # Candidate 4: Cleaned title without noise
    t_clean = ' '.join(re.sub(r'[#|\-]', ' ', t).split())
    if t_clean:
        candidates.append(t_clean)

    # Deduplicate while preserving order
    seen = set()
    unique_candidates = []
    for c in candidates:
        c_norm = ' '.join(c.split()).strip()
        if c_norm and c_norm.lower() not in seen:
            seen.add(c_norm.lower())
            unique_candidates.append(c_norm)

    return unique_candidates

def clean_youtube_query(raw_title: str, channel_author: str = '') -> str:
    """Extract a clean, high-precision search query from a messy YouTube title."""
    cands = get_search_candidates(raw_title, channel_author)
    return cands[0] if cands else (raw_title or '')

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

def normalize_proxy_url(proxy_str: str) -> str:
    """Convert ip:port:user:pass or existing http://user:pass@ip:port into standard http://user:pass@ip:port."""
    p = proxy_str.strip()
    if not p:
        return ""
    if p.startswith(('http://', 'https://', 'socks5://', 'socks5h://')):
        return p
    parts = p.split(':')
    if len(parts) == 4:
        ip, port, user, password = parts
        return f"http://{user}:{password}@{ip}:{port}"
    elif len(parts) == 2:
        ip, port = parts
        return f"http://{ip}:{port}"
    return f"http://{p}"

def get_proxy_list() -> list:
    proxy_env = os.getenv('YTDL_PROXY') or os.getenv('HTTP_PROXY')
    if not proxy_env:
        return []
    raw_list = re.split(r'[,\n]+', proxy_env.strip())
    clean_list = []
    for p in raw_list:
        p = p.strip()
        if p:
            norm = normalize_proxy_url(p)
            if norm:
                clean_list.append(norm)
    return clean_list

_cached_proxies = None

def get_ordered_proxies() -> list:
    """Return list of proxies, keeping known-working ones first."""
    global _cached_proxies
    all_proxies = get_proxy_list()
    if not all_proxies:
        return []
    if _cached_proxies is None:
        _cached_proxies = list(all_proxies)
    else:
        for p in all_proxies:
            if p not in _cached_proxies:
                _cached_proxies.append(p)
        _cached_proxies = [p for p in _cached_proxies if p in all_proxies]
    return list(_cached_proxies)

def mark_proxy_success(proxy: str):
    """Move successfully used proxy to front of the list for instant reuse."""
    global _cached_proxies
    if _cached_proxies and proxy in _cached_proxies:
        _cached_proxies.remove(proxy)
        _cached_proxies.insert(0, proxy)

def mark_proxy_failed(proxy: str):
    """Move failing proxy to the back of the list."""
    global _cached_proxies
    if _cached_proxies and proxy in _cached_proxies:
        _cached_proxies.remove(proxy)
        _cached_proxies.append(proxy)

def get_random_proxy() -> str:
    proxies = get_ordered_proxies()
    return proxies[0] if proxies else None

def log_proxy_status():
    proxies = get_proxy_list()
    if proxies:
        masked = [re.sub(r':([^:@/]+)@', ':****@', p) for p in proxies]
        print(f"[YTDL] {len(proxies)} Proxy(ies) configured! Example: {masked[0]}", flush=True)
    else:
        print("[YTDL] Notice: No YTDL_PROXY configured. Direct datacenter IP will be used.", flush=True)

log_proxy_status()

def get_ytdl_instance(noplaylist: bool = False, use_cookies: bool = True, proxy: str = None, player_clients: list = None):
    ensure_cookies_written()
    cookies_path = 'cookies.txt'
    
    # Default to android mobile client which bypasses YouTube's datacenter IP bot detection
    clients = player_clients or ['android']
    
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
        'socket_timeout': 8,
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
    
    if proxy:
        options['proxy'] = proxy
    
    if use_cookies and os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
        options['cookiefile'] = cookies_path

    return yt_dlp.YoutubeDL(options), proxy

def extract_youtube_info(target: str, noplaylist: bool = False):
    """Extract YouTube info with multi-proxy automatic failover. Returns (data, used_proxy) tuple."""
    ensure_cookies_written()
    cookies_available = os.path.exists('cookies.txt') and os.path.getsize('cookies.txt') > 0
    proxies = get_ordered_proxies()

    last_err = None

    # Step 1: Try each proxy with the android client (which bypasses bot check on good IPs)
    for p in proxies:
        masked = re.sub(r':([^:@/]+)@', ':****@', p)
        try:
            ydl, _ = get_ytdl_instance(
                noplaylist=noplaylist,
                use_cookies=False,
                proxy=p,
                player_clients=['android']
            )
            data = ydl.extract_info(target, download=False)
            if data:
                mark_proxy_success(p)
                return data, p
        except Exception as err:
            last_err = err
            mark_proxy_failed(p)
            print(f"[YTDL] Proxy {masked} failed for '{target}': {str(err).splitlines()[0]}", flush=True)

    # Step 2: Direct IP with android client (works if running locally or on unblocked server)
    try:
        ydl, _ = get_ytdl_instance(
            noplaylist=noplaylist,
            use_cookies=False,
            proxy=None,
            player_clients=['android']
        )
        data = ydl.extract_info(target, download=False)
        if data:
            return data, None
    except Exception as err:
        last_err = err
        print(f"[YTDL] Direct IP android client failed for '{target}': {str(err).splitlines()[0]}", flush=True)

    # Step 3: Web client with cookies (if available)
    if cookies_available:
        try:
            ydl, _ = get_ytdl_instance(
                noplaylist=noplaylist,
                use_cookies=True,
                proxy=None,
                player_clients=['web']
            )
            data = ydl.extract_info(target, download=False)
            if data:
                return data, None
        except Exception as err:
            last_err = err
            print(f"[YTDL] Web client with cookies failed for '{target}': {str(err).splitlines()[0]}", flush=True)

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

    # Filter out common modified/amateur tracks (slowed, reverb, raw acoustic cover, remixes, edm mashups)
    # unless the user specifically searched for those terms
    unwanted_keywords = [
        'slowed', 'reverb', 'slow+reverb', 'slowed+reverb', 
        'acoustic cover', 'guitar cover', 'unplugged cover', 'raw',
        'remix', 'mashup', 'edm', 'bootleg', 'bass boosted', 'bassboosted',
        'ringtone', 'status', 'shorts'
    ]
    for kw in unwanted_keywords:
        if kw in title and kw not in orig_q:
            return False

    # Relevance check: candidate title/uploader must share significant tokens with original_query
    if orig_q:
        q_words = [w for w in re.findall(r'\w+', orig_q) if w not in META_NOISE_WORDS and len(w) >= 2]
        if q_words:
            entry_text = f"{title} {str(entry.get('uploader', '')).lower()}"
            # Primary word check: first non-noise token (core song title) must be in entry_text
            if q_words[0] not in entry_text:
                return False
            matched_words = [w for w in q_words if w in entry_text]
            if len(matched_words) / len(q_words) < 0.5:
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

            # 2. If it's a YouTube URL (video or playlist) -> ALWAYS EXTRACT DIRECTLY FROM YOUTUBE FIRST!
            title_from_oembed = None
            author_from_oembed = None
            if is_url and ("youtube.com" in clean_search or "youtu.be" in clean_search):
                try:
                    res, _ = extract_youtube_info(clean_search, noplaylist=not is_explicit_playlist)
                    if res:
                        # If an explicit playlist returned 0 entries (e.g. invalid/deleted playlist), but has a video_id
                        if is_explicit_playlist and ('entries' in res) and not res['entries']:
                            parsed = urlparse.urlparse(clean_search)
                            qs = urlparse.parse_qs(parsed.query)
                            vid = qs.get('v', [None])[0]
                            if vid:
                                single_url = f"https://www.youtube.com/watch?v={vid}"
                                single_res, _ = extract_youtube_info(single_url, noplaylist=True)
                                return single_res
                        return res
                except Exception as e:
                    print(f"[YTDL Warning] Direct YouTube extraction failed for '{clean_search}': {e}. Trying fallbacks...", flush=True)
                    title_from_oembed, author_from_oembed = get_youtube_title_oembed(clean_search)

            # 4. Fallback / search resolution path
            target_title = title_from_oembed or clean_search
            exp_artist = extract_expected_artist(target_title, author_from_oembed)
            for cand in get_search_candidates(target_title, author_from_oembed):
                saavn_track = search_saavn(cand, expected_artist=exp_artist)
                if saavn_track:
                    return {'entries': [saavn_track]}

            query = clean_youtube_query(target_title, author_from_oembed)

            # YouTube search fallback
            try:
                yt_search_data, _ = extract_youtube_info(f"ytsearch1:{query}", noplaylist=True)
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
                        return {'entries': [valid_entries[0]]}
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
        uploader = track_info.get('uploader') if isinstance(track_info, dict) else ''
        clean_url = clean_youtube_url(webpage_url) if isinstance(webpage_url, str) else webpage_url
        
        def _extract():
            """Returns (data, used_proxy) tuple. used_proxy is the proxy that extracted the YouTube stream URL."""
            # If the URL is already a direct SoundCloud URL
            if isinstance(clean_url, str) and 'soundcloud.com' in clean_url:
                sc_ytdl = get_soundcloud_ytdl_instance()
                try:
                    res = sc_ytdl.extract_info(clean_url, download=False)
                    if res and is_valid_soundcloud_entry(res, title):
                        return res, None
                    if res and res.get('url'):
                        return res, None
                except Exception as sc_url_err:
                    print(f"[SoundCloud Warning] Direct SoundCloud extraction failed: {sc_url_err}", flush=True)

            # PRIORITY 1: If it's a YouTube URL -> ALWAYS EXTRACT DIRECT AUDIO FROM THAT EXACT YOUTUBE VIDEO FIRST!
            yt_proxy_used = None
            if isinstance(clean_url, str) and ('youtube.com' in clean_url or 'youtu.be' in clean_url):
                try:
                    yt_data, yt_proxy_used = extract_youtube_info(clean_url, noplaylist=True)
                    print(f"[Stream] Resolved via YouTube direct: '{title}'", flush=True)
                    return yt_data, yt_proxy_used
                except Exception as e:
                    print(f"[YTDL Warning] Direct YouTube stream extraction failed for '{title}': {e}. Trying fallbacks...", flush=True)

            # Fallback 1: Check JioSaavn with prioritized candidates AND expected artist verification!
            expected_artist = extract_expected_artist(title, uploader)
            for cand in get_search_candidates(title, uploader):
                saavn_track = search_saavn(cand, expected_artist=expected_artist)
                if saavn_track:
                    print(f"[Stream] Fallback to JioSaavn: '{title}' -> '{saavn_track.get('title')}'", flush=True)
                    return saavn_track, None

            cleaned_title = clean_youtube_query(title, uploader)

            # PRIORITY 3: SoundCloud search
            sc_ytdl = get_soundcloud_ytdl_instance()
            try:
                res = sc_ytdl.extract_info(f"scsearch5:{cleaned_title}", download=False)
                if res and 'entries' in res and res['entries']:
                    valid_entries = [e for e in res['entries'] if is_valid_soundcloud_entry(e, cleaned_title)]
                    if valid_entries:
                        print(f"[Stream] Resolved via SoundCloud: '{title}' -> '{valid_entries[0].get('title')}'", flush=True)
                        return valid_entries[0], None
                if res and is_valid_soundcloud_entry(res, cleaned_title):
                    return res, None
            except Exception as sc_err:
                print(f"[SoundCloud Warning] SoundCloud search failed: {sc_err}", flush=True)
            
            return None, None

        result = await loop.run_in_executor(None, _extract)
        data, extraction_proxy = result if result else (None, None)
        
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

        # CRITICAL: Use the SAME proxy for FFmpeg that was used for yt-dlp extraction!
        # YouTube stream URLs are IP-locked — if extracted via proxy X, FFmpeg must also use proxy X.
        # Only apply proxy for YouTube/googlevideo URLs (JioSaavn/SoundCloud don't need it).
        proxy_arg = ''
        is_youtube_stream = 'googlevideo.com' in filename or 'youtube.com' in filename
        if is_youtube_stream and extraction_proxy and extraction_proxy.startswith('http'):
            proxy_arg = f'-http_proxy "{extraction_proxy}" '
            print(f"[FFmpeg] Using same proxy as extraction for YouTube stream", flush=True)

        dynamic_ffmpeg_options = {
            'options': '-vn',
            'before_options': f'{proxy_arg}-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 10M -analyzeduration 10M -user_agent "{user_agent}"'
        }
        
        return cls(discord.FFmpegPCMAudio(filename, **dynamic_ffmpeg_options), data=data)
