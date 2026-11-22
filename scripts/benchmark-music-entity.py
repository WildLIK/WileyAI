"""Offline ranking only. Default tune; holdout requires a frozen code protocol."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.music_entity import rank, confident, words, phonetic, similarity
from core.music_intents import search_query

DATA = ROOT / 'tests/fixtures/music-entity'
OUTPUT = ROOT / 'docs/benchmarks/music-entity-c2.json'


def baseline(query, rows):
    # Frozen pre-C2 rank(), including its original variant list and difflib.
    def words(value): return re.findall(r'[\w]+', search_query(value).casefold().replace('ё', 'е'))
    wanted = words(query)
    if not wanted: return []
    results = []
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ('id', 'title', 'artists')) or not re.fullmatch(r'\d{1,30}', row['id']): continue
        actual = words(row['title'] + ' ' + row['artists'])
        coverage = sum(word in actual for word in wanted) / len(wanted)
        similarity = difflib.SequenceMatcher(None, ' '.join(sorted(wanted)), ' '.join(sorted(actual))).ratio()
        score = .65 * coverage + .35 * similarity
        if any(word in actual and word not in wanted for word in ('remix','live','reanimation','acoustic','slowed','sped','ремикс','кавер')): score -= .15
        results.append({**row, 'score':round(score,4)})
    return sorted(results,key=lambda row:row['score'],reverse=True)


def percentile(values, p):
    return round(sorted(values)[min(len(values)-1,int((len(values)-1)*p))],3) if values else 0


def metrics(results):
    positive=[r for r in results if r['expected']]
    negative=[r for r in results if not r['expected']]
    unique=[r for r in positive if r['auto_expected'] and r['top1'] in r['expected']]
    exact=[r for r in positive if r['kind']=='exact']
    return {'cases':len(results),'positive':len(positive),'negative':len(negative),
            'top1':sum(r['top1'] in r['expected'] for r in positive),
            'top3':sum(bool(set(r['top3'])&set(r['expected'])) for r in positive),
            'false_matches':sum(r['auto'] for r in negative),
            'wrong_autoplay_positive':sum(r['auto'] and r['top1'] not in r['expected'] for r in positive),
            'unnecessary_clarifications':sum(not r['auto'] for r in unique),'clarification_denominator':len(unique),
            'exact_top1':sum(r['top1'] in r['expected'] for r in exact),'exact_total':len(exact),
            'p50_ms':round(statistics.median(r['ms'] for r in results),3),'p95_ms':percentile([r['ms'] for r in results],.95)}


def run(split):
    path=DATA/(split+'.json')
    seal=json.loads((DATA/'sealed.json').read_text())
    assert hashlib.sha256(path.read_bytes()).hexdigest()==seal[split]
    if split=='holdout':
        protocol=json.loads((DATA/'protocol.json').read_text())
        assert protocol['code_sha256']==hashlib.sha256((ROOT/'core/music_entity.py').read_bytes()).hexdigest(),'Code changed after freeze'
    fixture=json.loads(path.read_text(encoding='utf-8'))
    assert fixture['meta']['catalogue_sha256']==hashlib.sha256((DATA/'catalogue.json').read_bytes()).hexdigest()
    catalogue=json.loads((DATA/'catalogue.json').read_text(encoding='utf-8'))['records']
    rows={r['id']:r for r in catalogue+fixture['synthetic_rows']}
    models={'baseline':baseline,'phonetic':lambda q,r:rank(q,r,mode='phonetic'),'combined':rank}
    result={}
    for name, scorer in models.items():
        for cache in (words, phonetic, similarity): cache.cache_clear()
        evaluated=[]
        for case in fixture['cases']:
            candidates=[rows[k] for k in case['candidate_ids']]
            began=time.perf_counter(); found=scorer(case['query'],candidates); ms=(time.perf_counter()-began)*1000
            evaluated.append({**{k:case[k] for k in ('id','kind','language','expected','auto_expected')},
                              'top1':found[0]['id'] if found else '', 'top3':[r['id'] for r in found[:3]],'auto':confident(found),'ms':round(ms,4)})
        result[name]={'summary':metrics(evaluated),'by_language':{k:metrics([r for r in evaluated if r['language']==k]) for k in ('ru','foreign_mixed')},'cases':evaluated}
        print(split,name,json.dumps(result[name]['summary']),flush=True)
    output=json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {}
    output.update({'fixture_only':True,'retrieval_recall':None,'retrieval_note':'Not measured: no authorized live Yandex search. Positive ranking pools contain the expected recording by construction.',
                   'candidate_pool_size':20,'negative_definition':'Absent requested artist/title pair; false match means score-threshold automatic acceptance, not merely top ranked suggestion.',
                   'phonetic_ablation':'Unsafe score-only ablation using the same .72/.05 thresholds; never used by the app.'})
    output[split]=result
    if split=='tune':
        performance={}
        real=[r for r in catalogue if r['split']=='tune'][:50]
        for name,scorer in models.items():
            cold=[];warm=[]
            for r in real[:20]:
                q=r['artists']+' '+r['title']
                for cache in (words,phonetic,similarity):cache.cache_clear()
                began=time.perf_counter();scorer(q,real);cold.append((time.perf_counter()-began)*1000)
                began=time.perf_counter();scorer(q,real);warm.append((time.perf_counter()-began)*1000)
            performance[name]={'cold_p50_ms':round(statistics.median(cold),3),'cold_p95_ms':percentile(cold,.95),
                               'warm_p50_ms':round(statistics.median(warm),3),'warm_p95_ms':percentile(warm,.95)}
        output['latency_50_rows']=performance
        print('50-row latency',json.dumps(performance),flush=True)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--split',choices=('tune','holdout'),default='tune')
    run(parser.parse_args().split)
