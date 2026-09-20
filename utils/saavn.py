import urllib.request
import urllib.parse
import json
import base64
import re

try:
    import pyDes
except ImportError:
    pyDes = None

_DES_KEY = b'38346591'
_STOPWORDS = {
    'official', 'video', 'song', 'audio', 'lyric', 'lyrics', 'lyrical',
    'music', 'full', 'track', '4k', 'hd', 'hq', '1080p', 'remastered',
    'the', 'a', 'an', 'and', 'by', 'in', 'of', 'to', 'feat', 'ft', 'with',
    'version', 'remix', 'prod', 'original', 'soundtrack', 'ost', 'from',
    'main', 'mein', 'tu', 'ki', 'ka', 'ke', 'se', 'hai', 'ho'
}

def is_saavn_match(query: str, song_title: str, singers: str, album: str = '') -> bool:
    """Verify that a JioSaavn candidate song authentically matches the query."""
    q_clean = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', query)
    noise_regex = r'\b(?:lyrical\s+video\s+song|lyrical\s+video|lyric\s+video|lyrical|lyrics|official\s+music\s+video|official\s+video\s+song|official\s+video|official\s+audio|music\s+video|video\s+song|full\s+video\s+song|full\s+video|full\s+song|full\s+audio|audio\s+song|audio\s+track|4k\s+ultra\s+hd|4k\s+hd|ultra\s+hd|1080p|remastered|video|audio|song)\b'
    q_clean = re.sub(noise_regex, ' ', q_clean, flags=re.IGNORECASE)
    q_clean = re.sub(r'[\"“”\']', ' ', q_clean)
    q_tokens = [w.lower() for w in re.findall(r'\w+', q_clean) if len(w) > 1 and w.lower() not in _STOPWORDS]
    if not q_tokens:
        return True

    c_title = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', song_title or '')
    c_title_tokens = [w.lower() for w in re.findall(r'\w+', c_title) if len(w) > 1 and w.lower() not in _STOPWORDS]
    if not c_title_tokens:
        return False

    c_singers = [w.lower() for w in re.findall(r'\w+', singers or '') if len(w) > 2 and w.lower() not in _STOPWORDS]
    c_full = f"{song_title} {singers} {album}".lower()
    c_tokens = set(re.findall(r'\w+', c_full))

    # 1. Title Similarity Check: At least one main word of candidate title must match or prefix-match query
    title_matched = any(
        ct in q_tokens or any(ct.startswith(qt) or qt.startswith(ct) for qt in q_tokens if min(len(ct), len(qt)) >= 4)
        for ct in c_title_tokens
    )
    if not title_matched:
        return False

    # 2. Artist Contradiction Check:
    # Check for unmatched query tokens (length >= 4) that don't appear anywhere in candidate
    unmatched_q_tokens = [
        qt for qt in q_tokens 
        if len(qt) >= 4 and qt not in c_tokens and not any(qt.startswith(ct) or ct.startswith(qt) for ct in c_tokens if min(len(ct), len(qt)) >= 4)
    ]
    
    # If the query contains unmatched distinctive words (like 'kaavish'),
    # but NONE of the candidate's singers/artists appear in the query:
    if unmatched_q_tokens:
        artist_in_query = any(s in q_tokens or any(s.startswith(qt) or qt.startswith(s) for qt in q_tokens) for s in c_singers)
        if not artist_in_query:
            return False

    # 3. Overall Token Overlap Ratio
    matched = [t for t in q_tokens if t in c_tokens or any(ct.startswith(t) or t.startswith(ct) for ct in c_tokens if min(len(ct), len(t)) >= 4)]
    overlap = len(matched) / len(q_tokens)
    return overlap >= 0.35

def decrypt_saavn_url(encrypted_url: str) -> str:
    """Decrypt JioSaavn's encrypted_media_url using DES-ECB."""
    if not encrypted_url:
        return None
    try:
        raw_bytes = base64.b64decode(encrypted_url)
        if pyDes:
            cipher = pyDes.des(_DES_KEY, pyDes.ECB, pad=None, padmode=pyDes.PAD_PKCS5)
            decrypted = cipher.decrypt(raw_bytes).decode('utf-8')
            return decrypted.strip()
    except Exception as e:
        print(f"[JioSaavn] Decryption error: {e}", flush=True)
    return None

def search_saavn(query: str):
    """
    Search JioSaavn for an authentic studio track.
    Returns metadata and direct 320kbps/160kbps audio CDN URL.
    Works from any datacenter IP (no bot detection, no IP locking).
    """
    if not query:
        return None

    cleaned = query.strip()
    # Clean up video keywords
    cleaned = re.sub(r'[\(\[][^\)\]]*(?:official|lyric|video|audio|visualizer|4k|hd|remix|version|prod|full song)[^\)\]]*[\)\]]', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(?:lyrical\s+video\s+song|lyrical\s+video|lyric\s+video|lyrical|lyrics|official\s+music\s+video|official\s+video\s+song|official\s+video|official\s+audio|music\s+video|video\s+song|full\s+video\s+song|full\s+video|full\s+song|full\s+audio|audio\s+song|audio\s+track|4k\s+ultra\s+hd|4k\s+hd|ultra\s+hd|1080p|remastered|video|audio|song)\b', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\"“”\']', '', cleaned)
    cleaned = ' '.join(cleaned.split()).strip()

    try:
        search_url = 'https://www.jiosaavn.com/api.php?__call=autocomplete.get&_format=json&_marker=0&cc=in&includeMetaTags=1&query=' + urllib.parse.quote(cleaned)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        req = urllib.request.Request(search_url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            
        songs = data.get('songs', {}).get('data', [])
        if not songs:
            return None

        # Find first song that authentically matches the search query
        matching_song = None
        for s in songs:
            s_title = s.get('title', '')
            more = s.get('more_info', {})
            s_singers = more.get('singers') or more.get('primary_artists') or s.get('description', '')
            s_album = s.get('album', '')
            if is_saavn_match(cleaned, s_title, s_singers, s_album):
                matching_song = s
                break

        if not matching_song:
            return None

        song_id = matching_song.get('id')
        if not song_id:
            return None

        # Fetch full song details
        details_url = f'https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_id}'
        req_details = urllib.request.Request(details_url, headers=headers)
        with urllib.request.urlopen(req_details, timeout=7) as resp_details:
            data_details = json.loads(resp_details.read().decode('utf-8'))
            
        song_info = data_details.get(song_id, {})
        enc_url = song_info.get('encrypted_media_url')
        if not enc_url:
            return None

        dec_url = decrypt_saavn_url(enc_url)
        if not dec_url:
            return None

        # Upgrade to 320kbps high quality stream
        stream_url = dec_url.replace('_96.mp4', '_320.mp4')

        song_title = song_info.get('song') or songs[0].get('title')
        singers = song_info.get('singers') or songs[0].get('description')
        duration = int(song_info.get('duration', 0))

        print(f"[JioSaavn] Resolved '{query}' -> '{song_title}' ({singers}) [320kbps]", flush=True)

        return {
            'title': f"{song_title} - {singers}" if singers else song_title,
            'url': stream_url,
            'webpage_url': song_info.get('perma_url') or f"https://www.jiosaavn.com/song/{song_id}",
            'uploader': singers or 'JioSaavn',
            'duration': duration,
            'http_headers': headers,
            'extractor': 'jiosaavn'
        }
    except Exception as e:
        print(f"[JioSaavn] Search failed for '{query}': {e}", flush=True)
        return None
