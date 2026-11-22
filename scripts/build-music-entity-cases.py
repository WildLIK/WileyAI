"""Deterministic fixture construction, independent of the production scorer."""
import hashlib
import json
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/music-entity'
# Test-only mechanical transcript generation, not an artist-name dictionary.
CYR = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', ['a','b','v','g','d','e','yo','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','kh','ts','ch','sh','sch','','y','','e','yu','ya']))
assert len(CYR) == 33
LATIN = dict(zip('abcdefghijklmnopqrstuvwxyz', ['а','б','к','д','е','ф','г','х','и','дж','к','л','м','н','о','п','к','р','с','т','у','в','в','кс','и','з']))


def transcript(value, language):
    value = value.casefold()
    if language == 'ru': return ''.join(CYR.get(c,c) for c in value)
    for a,b in [('sh','ш'),('ch','ч'),('th','з'),('ph','ф'),('ee','и'),('oo','у')]: value=value.replace(a,b)
    return ''.join(LATIN.get(c,c) for c in value)


def typo(value):
    # One deterministic deleted interior letter per long word; no scorer use.
    return re.sub(r'\w{6,}', lambda m:m[0][:3]+m[0][4:],value)


def build():
    source = DEST/'catalogue.json'
    data=json.loads(source.read_text(encoding='utf-8'))
    catalogue=data['records']
    seal={}
    for split in ('tune','holdout'):
        real=[r for r in catalogue if r['split']==split]
        cases=[]; controls=[]
        for index,row in enumerate(real):
            rng=random.Random(6317+int(row['id']))
            others=[r for r in real if r['id']!=row['id']]
            rng.shuffle(others)
            same=[r for r in real if r['artists']==row['artists'] and r['id']!=row['id']]
            pool=list(dict.fromkeys([row['id'],*[r['id'] for r in same[:4]],*[r['id'] for r in others]]))[:17]
            versions=[]
            for n,version in enumerate(('Live','Remix','Cover')):
                v={**row,'id':str(9000000+int(row['id'])*3+n),'title':row['title']+' ('+version+')','synthetic_control':True}
                controls.append(v); versions.append(v['id'])
            pool+=versions
            exact=row['artists']+' '+row['title']
            variant = transcript(exact,row['language']) if index%3==0 else typo(exact) if index%3==1 else row['artists']+' — '+transcript(row['title'],row['language'])
            def add(kind,query,expected,auto_expected=True):
                cases.append({'id':f'{split}-{row["id"]}-{kind}','kind':kind,'language':row['language'],'group':row['group'],
                              'query':query,'expected':expected,'candidate_ids':pool,'auto_expected':auto_expected})
            add('exact',exact,[row['id']])
            add('distorted',variant,[row['id']])
            other=next(r for r in others if r['group']!=row['group'])
            add('absent_artist',other['artists']+' QZX — '+row['title'],[],False)
            if index%10==0: add('requested_live',row['artists']+' '+row['title']+' Live',[versions[0]])
        payload={'meta':{'catalogue_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                         'generation':'v2 generator (corrected letter table); artist-disjoint groups; synthetic transcript and version controls',
                         'retrieval':'not measured: correct candidate deliberately present for positive ranking cases'},
                 'cases':cases,'synthetic_rows':controls}
        path=DEST/(split+'.json')
        if path.exists(): raise ValueError('Frozen fixture already exists: '+str(path))
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        seal[split]=hashlib.sha256(path.read_bytes()).hexdigest()
        print(split,len(real),'real tracks',len(cases),'queries')
    (DEST/'sealed.json').write_text(json.dumps(seal,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__': build()
