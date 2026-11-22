"""Produce reviewable NEXT 12 CSV and summary metrics from frozen replay JSON."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

import numpy as np


def display(hit):
    if not hit:
        return ''
    return '; '.join(f"{item['sample']/16000:.3f} {item['why']}" for item in hit)


def report(root):
    all_metrics={}
    case_table=[]
    for group in ('development','historical','public'):
        matches=sorted(root.glob(f'{group}-verified.json'))
        if not matches:
            raise ValueError('Missing verified run '+group)
        d=json.loads(matches[0].read_text(encoding='utf8'))
        rows=d['inputs']
        methods=tuple(rows[0]['hits'])
        total=Counter()
        counts={}
        timing={}
        for r in rows:
            total.update(r['cpu_s'])
            if group!='public' or any(r['hits'].values()):
                item=dict(group=group,id=r['id'],label=r.get('label',''),kind=r['category'],
                    final='; '.join(f"{e['text']} @ {e['sample']/16000:.3f}" for e in r['trace'] if e['text']))
                item.update({m:display(r['hits'][m]) for m in methods})
                item['allowed_mention']=bool(r['id'].startswith('c630110a') and any(
                    22.38<=e['sample']/16000<=23.38 for e in r['hits']['multi']))
                case_table.append(item)
        subsets={'positive':[r for r in rows if r['expected']],
                 'negative':[r for r in rows if not r['expected']]}
        subsets.update({cat:[r for r in rows if r['category']==cat] for cat in {r['category'] for r in rows}})
        for phrase in {r.get('label','') for r in rows if r['expected']}:
            subsets[phrase]=[r for r in rows if r.get('label')==phrase]
        for name,subset in subsets.items():
            counts[name]=dict(n=len(subset),clips={m:sum(bool(r['hits'][m]) for r in subset) for m in methods},
                            events={m:sum(len(r['hits'][m]) for r in subset) for m in methods})
        if group=='historical':
            for method in methods:
                lags=[r['hits'][method][0]['sample']/16000-r['verified_end_s']
                      for r in rows if r['hits'][method]]
                in_time=[v*1000 for v in lags if 0<=v<=1.5]
                timing[method]=dict(in_time=len(in_time),early=sum(v<0 for v in lags),
                    late=sum(v>1.5 for v in lags),p50_p95_ms=np.percentile(in_time,[50,95]).tolist() if in_time else None)
        all_metrics[group]=dict(seconds=sum(r['samples'] for r in rows)/16000,counts=counts,
            word_end=timing,cpu_seconds=dict(total),prefix_wall_total_ms=sum(r['prefix_wall_s'] for r in rows)*1000,
            candidate_requests=sum(r['confirmation_requests'] for r in rows),memory=d['model'])
    with (root/'cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(case_table[0]))
        writer.writeheader()
        writer.writerows(case_table)
    (root/'summary.json').write_text(json.dumps(all_metrics,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    report(p.parse_args().directory)

