"""Create event-level CSV and unique hit counts from replay-wake-diagnostics --timeline."""
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

RATE = 16000


def correlate(data, labels):
    rows = []
    recog = {(r["session_id"], r["id"]): r for r in data["recognition"]}
    unique = []
    for island in data["islands"]:
        def belongs(event):
            return (event["session_id"] == island["session_id"] and event["capture_id"] == island["capture_id"]
                    and island["start"] <= event["source_start"] and event["source_start"] + event["samples"] <= island["end"])
        group = sorted(filter(belongs, data["events"]), key=lambda e: e["capture_sample"])
        if not group:
            raise ValueError("No source events for island")
        routes = sorted((r for r in data["routes"] if (r["session_id"], r["capture_id"]) ==
                        (island["session_id"], island["capture_id"])), key=lambda r: r["elapsed_ms"])
        targets = []
        for e in group:
            event_id = e["id"]
            rec = recog.get((e["session_id"], event_id), {})
            final = rec.get("vosk_final", {})
            words = final.get("result", [])
            route = next((r for r in reversed(routes) if r["elapsed_ms"] <= e["elapsed_ms"]), {})
            accepted = e.get("accepted") is True
            annotated = labels.get("by_session", {}).get(e["session_id"], {}).get(event_id)
            date = e["utc"][:10]
            no_calls = date in labels.get("no_intent_utc_dates", [])
            label = annotated or ("owner_false" if no_calls and accepted else "no_intent_period" if no_calls else "unclassified")
            row = dict(id=event_id, utc=e["utc"], session_id=e["session_id"], capture_id=e["capture_id"],
                       archive_label=e["label"], owner_label=label, kind=e["kind"], live_accepted=e.get("accepted"),
                       decision=e.get("decision"), vosk_final=final.get("text"), confidence=e.get("confidence"),
                       source_start=e["source_start"], capture_sample=e["capture_sample"], pre=e["pre_samples"],
                       post=e["post_samples"], input_type=route.get("input_type"), media_active=route.get("media_active"),
                       media_app=route.get("media_app"), media_volume=route.get("media_volume"),
                       route_age_ms=e["elapsed_ms"]-route["elapsed_ms"] if route else None,
                       partial=[r["text"] for r in rec.get("partial",[])], window=e.get("window_outcome"))
            if words and accepted:
                lo, hi = round(words[0]["start"]*RATE), round(words[-1]["end"]*RATE)
                if not e["source_start"] <= lo < hi <= e["capture_sample"]:
                    raise ValueError("Word timestamps inconsistent with capture clock")
                row.update(word_start=lo,word_end=hi,lag_ms=e.get("reported_lag_ms"))
                targets.append((lo,hi,e["capture_sample"],event_id))
            for name, model in island["models"].items():
                clip_lo = e["source_start"] - island["start"]
                clip_hi = clip_lo + e["samples"]
                row[name+"_clip_hits"] = [p+island["start"] for p in model["hits"] if clip_lo < p <= clip_hi]
                if accepted and words:
                    if "scores" in model:
                        relevant = [(p+island["start"],s) for p,s in model["scores"]
                                    if lo <= p+island["start"] <= e["capture_sample"]]
                        row[name+"_target_peak"] = max((s for _,s in relevant), default=None)
                        row[name+"_target_hits"] = [p for p in row[name+"_clip_hits"] if lo <= p <= e["capture_sample"]]
                    else:
                        row[name+"_target_hits"] = [r["sample"]+island["start"] for r in model["finals"] if r["accepted"]
                                and matching_words(r["words"], island["start"], lo, hi)]
            if accepted and words and "plix_next6" in island["models"]:
                row["comparison"] = "plix_also_triggered" if row["plix_next6_target_hits"] else "no_plix_trigger_at_candidate"
            rows.append(row)
        for name, model in island["models"].items():
            by_position = {r["sample"]:r for r in model.get("finals",[]) if r["accepted"]}
            scores = dict(model.get("scores",[]))
            for pos in model["hits"]:
                absolute = island["start"]+pos
                near = min(group,key=lambda e:abs(e["capture_sample"]-absolute))
                utc = datetime.fromisoformat(near["utc"].replace("Z","+00:00")) + timedelta(seconds=(absolute-near["capture_sample"])/RATE)
                hit_targets = [eid for lo,hi,decision,eid in targets if (
                    matching_words(by_position[pos]["words"],island["start"],lo,hi) if name=="vosk" else lo<=absolute<=decision)]
                unique.append(dict(model=name,session_id=island["session_id"],capture_id=island["capture_id"],
                                   sample=absolute,utc_estimate=utc.astimezone(timezone.utc).isoformat(),
                                   date_no_intent=utc.date().isoformat() in labels.get("no_intent_utc_dates",[]),
                                   score=scores.get(pos),confidence=by_position.get(pos,{}).get("confidence"),
                                   associated_ids=hit_targets, source_ids=[e["id"] for e in group
                                       if e["source_start"] < absolute <= e["source_start"] + e["samples"]]))
    if len(rows) != len(data["events"]):
        raise ValueError("Source events were lost or counted twice")
    return sorted(rows,key=lambda r:r["utc"]), unique


def matching_words(words, origin, lo, hi):
    if not words:
        return False
    left = origin+round(words[0]["start"]*RATE)
    right = origin+round(words[-1]["end"]*RATE)
    duration = min(hi-lo, right-left)
    return duration > 0 and min(hi,right)-max(lo,left) >= duration/2


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("timeline",type=Path)
    p.add_argument("--labels",type=Path)
    p.add_argument("--out-dir",type=Path,required=True)
    args=p.parse_args()
    d=json.loads(args.timeline.read_text(encoding="utf8"))
    labels=json.loads(args.labels.read_text(encoding="utf8")) if args.labels else {}
    records,hits=correlate(d,labels)
    args.out_dir.mkdir(parents=True,exist_ok=True)
    for name,selected in (("classification.csv",records),("accepted.csv",[r for r in records if r["live_accepted"]])):
        with (args.out_dir/name).open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=sorted(set().union(*(r.keys() for r in selected))))
            writer.writeheader()
            for r in selected:
                writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})
    (args.out_dir/"unique-hits.json").write_text(json.dumps(hits,indent=2),encoding="utf8")


if __name__=="__main__":
    main()
