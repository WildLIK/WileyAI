"""Explicit public CC0 metadata fetch; never used by the app or normal tests."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/music-entity'
ARTISTS = {
    'ru': ['Кино', 'Земфира', 'ДДТ', 'Сплин', 'Би-2', 'Мумий Тролль', 'Наутилус Помпилиус', 'Алиса', 'Чайф', 'Ария', 'Король и Шут', 'Пикник', 'Машина времени', 'Мельница', 'Михаил Круг', 'Каста'],
    'foreign_mixed': ['Linkin Park', 'Noize MC', 'Rammstein', 'Imagine Dragons', 'Billie Eilish', 'Queen', 'Daft Punk', 'Twenty One Pilots', 'Metallica', 'Nightwish', 'Radiohead', 'Nirvana', 'Björk', 'Massive Attack', 'Depeche Mode', 'AC/DC'],
}


def key(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    return ''.join(c for c in value if c.isalnum())


def fetch():
    DEST.mkdir(parents=True, exist_ok=True)
    records, requests = [], []
    with httpx.Client(timeout=25, follow_redirects=True, headers={'User-Agent': 'WileyAI-C2-OfflineBenchmark/1.0 (public music metadata research)'}) as client:
        for language, artists in ARTISTS.items():
            for index, artist in enumerate(artists):
                url = 'https://musicbrainz.org/ws/2/recording/'
                params = {'query': 'artist:"' + artist + '"', 'limit': 100, 'fmt': 'json'}
                rows, seen = [], set()
                def retrieve(query, offset=0):
                    params = {'query': query, 'limit': 100, 'fmt': 'json', 'offset': offset}
                    cache = ROOT / 'local/review/c2-metadata-cache'
                    cache.mkdir(parents=True, exist_ok=True)
                    cache_path = cache / (hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()[:16] + '.json')
                    if cache_path.exists(): return json.loads(cache_path.read_text(encoding='utf-8'))
                    for attempt in range(3):
                        time.sleep(1.1)
                        response = client.get(url, params=params)
                        if response.status_code == 200: break
                    response.raise_for_status()
                    payload = response.json()
                    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                    return payload
                from collections import Counter
                probe = retrieve(params['query'])
                ids = Counter(c['artist']['id'] for r in probe.get('recordings',[]) for c in r.get('artist-credit',[])
                              if key(artist) in {key(c.get('name','')),key(c.get('artist',{}).get('name','')),*(key(a['name']) for a in c.get('artist',{}).get('aliases',[]))})
                if not ids: raise ValueError('No verified artist id: ' + artist)
                artist_id = ids.most_common(1)[0][0]
                raw=[]
                for offset in (0,100,200):
                    payload=retrieve('arid:' + artist_id,offset)
                    raw.extend(payload.get('recordings',[]))
                    if len({key(r['title']) for r in raw}) >= 30 or offset+100 >= payload.get('count',0): break
                for row in raw:
                    credits = row.get('artist-credit', [])
                    if not any(c['artist']['id'] == artist_id for c in credits): continue
                    title = row['title']
                    if len(title) < 3 or len(title) > 120 or re.search(r'\b(?:live|remix|remastered|demo|cover)\b', title, re.I): continue
                    if language == 'ru' and not re.search('[А-Яа-яЁё]', title): continue
                    if key(title) in seen: continue
                    seen.add(key(title))
                    credit = ''.join(c.get('name', '') + c.get('joinphrase', '') for c in credits)
                    rows.append({'id': str(10000 + len(records) + len(rows)), 'title': title, 'artists': credit,
                                 'mbid': row['id'], 'artist_mbids': [c['artist']['id'] for c in credits],
                                 'source': 'https://musicbrainz.org/recording/' + row['id'], 'language': language,
                                 'group': artist, 'split': 'tune' if index < 4 else 'holdout'})
                    if len(rows) == 10: break
                if len(rows) != 10: raise ValueError(f'{artist}: only {len(rows)} eligible titles; do not silently shrink dataset')
                records.extend(rows)
                requests.append({'artist': artist, 'url': str(httpx.URL(url, params={k:v for k,v in params.items() if k!='offset'}))})
                print(language, index + 1, 'tracks', len(records), flush=True)
    data = {'meta': {'source': 'MusicBrainz core metadata', 'license': 'CC0-1.0', 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                     'note': 'Public metadata, not Yandex search results. Numeric ids are fixture ids, not Yandex ids.', 'requests': requests}, 'records': records}
    path = DEST / 'catalogue.json'
    if path.exists(): raise ValueError('Existing catalogue is frozen; choose a new fixture path/version')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('catalogue SHA256', hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-public-metadata', action='store_true', required=True)
    parser.parse_args()
    fetch()
