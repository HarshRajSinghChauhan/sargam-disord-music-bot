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
    cleaned = re.sub(r'[\(\[][^\)\]]*(?:official|lyric|video|audio|visualizer|4k|hd|remix|version|prod|full song)[^\)\]]*[\)\]]', '', cleaned, flags=re.IGNORECASE)
    if '|' in cleaned:
        cleaned = cleaned.split('|')[0]
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

        # Pick best matching song
        song_id = songs[0].get('id')
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
