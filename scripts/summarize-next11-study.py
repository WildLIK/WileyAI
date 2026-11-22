"""Join decisions, targeted hypotheses and recommended owner reviews without exposing audio."""
import argparse
import csv
import json
from pathlib import Path


def run(directory):
    def read(name):
        return json.loads((directory/name).read_text(encoding='utf8'))

    replay=read('replay-results.json')
    details={row['id']:row for row in read('negative-review.json')}
    headers=('id','group','label','android_vosk','gigaam','wide_vosk','vosk_final',
             'detector_scores','status','notes')
    problems=[]
    rows=[]
    negative=[]
    for e in replay['samples']:
        row=e['row']
        is_positive=row['kind']=='positive'
        decisions={key:bool(value['hits']) for key,value in e['detectors'].items()}
        bad=[key for key,value in decisions.items() if value!=is_positive]
        scores={key:dict(hits=value['hits'],peak=row.get(key+'_peak')) for key,value in e['detectors'].items()}
        scores['vosk']['accepted_confidences']=[value['confidence'] for value in e['detectors']['vosk']['finals'] if value['accepted']]
        messages=[]
        errors=[]
        if is_positive and bad:
            errors.append('miss')
            messages.append('Проверить произнесённое имя и конец слова по записи.')
        if not is_positive and bad:
            errors.append('false_positive')
            messages.append('Проверить речь в интервале срабатывания.')
        if (row['vosk_archive']=='accepted')!=decisions['vosk']:
            errors.append('android_pc_difference')
            messages.append('На телефоне и ПК различаются решение или уверенность Vosk.')
        if not row['gigaam']:
            errors.append('gigaam_empty')
            messages.append('GigaAM не вернула текст полного клипа. Проверить исходную речь и локальные подотрезки.')
        hypotheses=details.get(row['id'],{}).get('events',[])
        review=dict(id=row['id'],group=row['category'],label=row['original_phrase'],android_vosk=row['vosk_archive'],
                    gigaam=row['gigaam'],wide_vosk=row['free_vosk'],vosk_final=row['vosk_finals'],
                    detector_scores=json.dumps(scores,ensure_ascii=False,separators=(',',':')),
                    status=','.join(errors) or 'ok',notes=' '.join(messages))
        rows.append(review)
        if errors: problems.append(dict(id=row['id'],category=row['category'],errors=errors,models=bad,
                                        near_detections=hypotheses,owner_review=bool(messages)))
        if not is_positive:
            negative.append(dict(review,around_detections=json.dumps(hypotheses,ensure_ascii=False)))
    for name,fields,items in [('case-review.csv',headers,rows),('negatives.csv',(*headers,'around_detections'),negative)]:
        with (directory/name).open('x',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            writer.writerows(items)
    errors=read('errors.json')
    errors['review']=problems
    (directory/'errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    run(p.parse_args().directory)

