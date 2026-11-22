"""Bounded catalogue ranking. Phonetics proposes candidates, not playback proof."""
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
import re
import unicodedata

from .app_discovery import sound_key
from .music_intents import search_query

VERSIONS = ('remix', 'live', 'reanimation', 'acoustic', 'slowed', 'sped', 'ремикс', 'кавер', 'cover')
LETTERS = {'эй': 'a', 'би': 'b', 'си': 'c', 'ди': 'd', 'и': 'e', 'эф': 'f', 'джи': 'g', 'эйч': 'h', 'ай': 'i',
           'джей': 'j', 'кей': 'k', 'эл': 'l', 'эм': 'm', 'эн': 'n', 'оу': 'o', 'пи': 'p', 'кью': 'q', 'ар': 'r',
           'эс': 's', 'ти': 't', 'ю': 'u', 'ви': 'v', 'даблъю': 'w', 'экс': 'x', 'уай': 'y', 'зэд': 'z'}


@lru_cache(maxsize=4096)
def words(value):
    value = unicodedata.normalize('NFKC', value.casefold().replace('ё', 'е'))
    # Fold Latin accents without conflating Cyrillic й and и.
    value = ''.join(''.join(c for c in unicodedata.normalize('NFKD', char) if not unicodedata.combining(c))
                    if 'LATIN' in unicodedata.name(char, '') else char for char in value)
    return tuple(re.findall(r'\w+', value))[:40]


@lru_cache(maxsize=4096)
def phonetic(value):
    # Reuse app discovery's transliteration, token by token so music titles
    # ending in years/numbers are not treated as software version suffixes.
    key = ''.join(sound_key(LETTERS.get(w, w)) for w in words(value))
    for source, target in (('dzh', 'j'), ('zh', 'j'), ('ph', 'f'), ('sch', 'sh'), ('sh', 's'), ('ch', 'c'), ('th', 't'), ('ck', 'k'), ('qu', 'kv'), ('w', 'v'), ('z', 's')):
        key = key.replace(source, target)
    key = re.sub(r'[aeiouy]', '', key)
    return re.sub(r'(.)\1+', r'\1', key)


@lru_cache(maxsize=8192)
def similarity(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def component(wanted, actual, mode='combined'):
    wanted, actual = words(wanted), words(actual)
    if not wanted or not actual: return 0.0
    # Greedy one-to-one word alignment: one common short token cannot cover
    # every word of an unrelated artist or title.
    remaining = list(actual)
    total = 0.0
    for token in sorted(wanted, key=len, reverse=True):
        if not remaining: break
        def score(other):
            lex = similarity(token, other)
            ph = similarity(phonetic(token), phonetic(other))
            return lex if mode == 'lexical' else ph if mode == 'phonetic' else max(lex, ph)
        best = max(range(len(remaining)), key=lambda i: score(remaining[i]))
        total += score(remaining.pop(best))
    return total / len(wanted)


def valid_rows(rows):
    return [row for row in rows if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ('id', 'title', 'artists'))
            and re.fullmatch(r'\d{1,30}', row['id']) and row['title'].strip()]


def legacy_score(query, row):
    """Original lexical formula, retained as a floor and benchmark baseline."""
    def old_words(value): return re.findall(r'[\w]+', search_query(value).casefold().replace('ё', 'е'))
    wanted, actual = old_words(query), old_words(row['title'] + ' ' + row['artists'])
    if not wanted: return 0.0
    return .65 * sum(w in actual for w in wanted) / len(wanted) + .35 * similarity(' '.join(sorted(wanted)), ' '.join(sorted(actual)))


def explicit_fields(query):
    marker = re.fullmatch(r'(.+?)\s+группы\s+(.+)', query, re.I)
    if marker: return marker[2], marker[1]
    marker = re.fullmatch(r'(.+?)\s+[—–-]\s+(.+)', query)
    return (marker[1], marker[2]) if marker else None


def rank(query, rows, *, mode='combined'):
    wanted = words(search_query(query))
    if not wanted: return []
    rows = valid_rows(rows)
    fields = explicit_fields(query)
    query_key = ' '.join(wanted)
    # An artist literally present in the query outranks phonetic neighbours.
    exact_artists = {words(r['artists']) for r in rows if words(r['artists']) and
                     re.search(r'(?<!\w)' + re.escape(' '.join(words(r['artists']))) + r'(?!\w)', query_key)}
    results = []
    for row in rows:
        actual = words(row['title'] + ' ' + row['artists'])
        penalty = .15 if any(v in actual and v not in wanted for v in VERSIONS) else 0
        old = legacy_score(query, row)
        if mode == 'lexical':
            results.append({**row, 'score': round(old - penalty, 4)})
            continue
        soft = component(' '.join(wanted), ' '.join(actual), mode)
        whole = similarity(phonetic(' '.join(wanted)), phonetic(' '.join(actual)))
        score = .65 * soft + .35 * whole
        artist_lex = title_lex = artist_soft = title_soft = None
        field_safe = True
        row_fields = fields
        if not row_fields:
            for known, kind in ((words(row['artists']), 'artist'), (words(row['title']), 'title')):
                if known and len(wanted) > len(known):
                    for offset in range(len(wanted) - len(known) + 1):
                        if wanted[offset:offset + len(known)] == known:
                            rest = ' '.join(wanted[:offset] + wanted[offset + len(known):])
                            row_fields = (' '.join(known), rest) if kind == 'artist' else (rest, ' '.join(known))
                            break
                if row_fields: break
        if row_fields:
            artist, title = row_fields
            artist_lex, title_lex = component(artist, row['artists'], 'lexical'), component(title, row['title'], 'lexical')
            artist_soft, title_soft = component(artist, row['artists'], mode), component(title, row['title'], mode)
            score = .5 * artist_soft + .5 * title_soft
            field_safe = artist_lex >= .85 and title_lex >= .85
        if mode == 'combined': score = max(score, old)
        title_exact = wanted == words(row['title'])
        whole_exact = Counter(wanted) == Counter(actual)
        if mode == 'combined' and (title_exact or whole_exact): score = 1.0
        conflict = bool(exact_artists and words(row['artists']) not in exact_artists)
        if conflict: score -= .25
        numbers = Counter(re.findall(r'\d+', query))
        number_conflict = bool(numbers - Counter(re.findall(r'\d+', row['title'] + ' ' + row['artists'])))
        if number_conflict: score -= .25
        score = max(0.0, min(1.0, score - penalty))
        artist_only = wanted == words(row['artists'])
        field_floor = .35 if not fields and title_lex is not None and title_lex >= .9 else .55
        plausible = score >= .5 and not number_conflict and (not row_fields or min(artist_soft, title_soft) >= field_floor)
        safe = (old >= .72 or title_exact or whole_exact) and field_safe and not artist_only and not conflict and plausible
        # The phonetic-only branch is an offline ablation, never used by CDP.
        if mode == 'phonetic': safe = True
        evidence = {'lexical': round(old, 4), 'alignment': round(soft, 4), 'autoplay_safe': safe, 'plausible': plausible,
                    'artist_conflict': conflict, 'artist_only': artist_only}
        if row_fields: evidence.update(artist_lexical=round(artist_lex, 4), title_lexical=round(title_lex, 4))
        results.append({**row, 'score': round(score, 4), 'match': evidence, '_exact': (2 if whole_exact else 1 if title_exact else 0) if mode == 'combined' else 0})
    results.sort(key=lambda row: (row.get('_exact', 0), row['score']), reverse=True)
    for row in results: row.pop('_exact', None)
    return results


def confident(rows):
    return bool(rows and rows[0]['score'] >= .72 and (len(rows) == 1 or rows[0]['score'] - rows[1]['score'] >= .05)
                and rows[0].get('match', {}).get('autoplay_safe', True) and rows[0].get('match', {}).get('plausible', True))


def alternatives(query, rows):
    """At most two readable variants, grounded in returned metadata, not keys."""
    variants = []
    cleaned = search_query(query).strip()
    if cleaned and cleaned != query and len(cleaned) <= 200: variants.append(cleaned)
    for row in rows[:3]:
        fields = explicit_fields(query)
        title = fields[1] if fields else query
        # Removing a noisy artist must not turn any random catalogue row into
        # a guessed query. Require a literal title anchor and phonetic support.
        title_anchor = set(words(title)) & {w for w in words(row['title']) if len(w) >= 4}
        if not title_anchor or component(row['title'], title, 'lexical') < .85: continue
        if component(query, row['artists'] + ' ' + row['title']) < .55: continue
        candidate = (row['artists'] + ' ' + row['title']).strip()
        if candidate != query and candidate not in variants and len(candidate) <= 200: variants.append(candidate)
        if len(variants) == 2: break
    return variants[:2]
