"""Local review of owner wake-word annotations. Original ZIP and proposals stay read-only."""
from __future__ import annotations
import csv, io, json, os, re, tempfile, threading, wave, zipfile
from pathlib import Path

ID = re.compile(r"^[0-9a-f-]{36}$")
FIELDS = ("id", "phrase", "wake_start_s", "wake_end_s", "status")

def read_wav(archive: Path, ident: str) -> tuple[bytes, float]:
    if not ID.fullmatch(ident): raise ValueError("Invalid sample identifier")
    with zipfile.ZipFile(archive) as z:
        info = z.getinfo(ident + ".wav")
        if info.file_size > 1024 * 1024: raise ValueError("Recording is too large")
        raw = z.read(info)
    with wave.open(io.BytesIO(raw)) as f:
        if (f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getcomptype()) != (1,2,16000,"NONE"):
            raise ValueError("Expected 16 kHz mono PCM16 WAV")
        return f.readframes(f.getnframes()), f.getnframes()/16000

def clipped_wav(pcm: bytes, start: float, end: float) -> bytes:
    duration = len(pcm)/32000
    if not (0 <= start < end <= duration): raise ValueError("Границы должны быть внутри записи")
    start_i, end_i = round(start*16000)*2, round(end*16000)*2
    out=io.BytesIO()
    with wave.open(out,"wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(pcm[start_i:end_i])
    return out.getvalue()

def save_review(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.wake-review-',suffix='.csv',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
        os.replace(temp,path)
    except BaseException:
        if os.path.exists(temp): os.unlink(temp)
        raise

def main() -> None:
    import argparse, tkinter as tk
    from tkinter import ttk, messagebox
    import winsound
    p=argparse.ArgumentParser(); p.add_argument('--archive',type=Path,default=Path('local/wakeword26b/owner-export-20261116-184820.zip'));p.add_argument('--proposals',type=Path,default=Path('local/wakeword26b/owner-annotations-wakegrammar-proposals.csv'));p.add_argument('--reviewed',type=Path,default=Path('local/wakeword26b/owner-annotations-reviewed.csv'));a=p.parse_args()
    if len({x.resolve() for x in (a.archive,a.proposals,a.reviewed)}) != 3: raise ValueError('Input and output files must be distinct')
    with a.proposals.open(encoding='utf-8-sig',newline='') as f: proposals=list(csv.DictReader(f))
    if not proposals or len({r['id'] for r in proposals}) != len(proposals): raise ValueError('Invalid proposal list')
    prior={}
    if a.reviewed.exists():
        with a.reviewed.open(encoding='utf-8-sig',newline='') as f: prior={r['id']:r for r in csv.DictReader(f)}
        if not set(prior).issubset({r['id'] for r in proposals}): raise ValueError('Reviewed file contains unknown samples')
    rows=[{k:(prior.get(r['id'],{}).get(k) if prior.get(r['id'],{}).get(k) is not None else r.get(k,'')) for k in FIELDS} for r in proposals]
    rows.sort(key=lambda r: (not (r.get('wake_start_s') and r.get('wake_end_s') and float(r['wake_end_s'])-float(r['wake_start_s'])<.28),r['id']))
    root=tk.Tk();root.title('WileyAI — локальная проверка обращения');root.geometry('1050x670');root.minsize(800,500)
    frame=ttk.Frame(root,padding=12);frame.pack(fill='both',expand=True); sidebar=tk.Listbox(frame,width=25,exportselection=False);sidebar.pack(side='left',fill='y');body=ttk.Frame(frame,padding=(12,0));body.pack(side='left',fill='both',expand=True)
    heading=ttk.Label(body,text='',font=('Segoe UI',14,'bold'));heading.pack(anchor='w'); instruction=ttk.Label(body,text='Для «Окей, Вайли» выделяйте только слово «Вайли». Короткие границы показаны первыми.');instruction.pack(anchor='w')
    canvas=tk.Canvas(body,height=200,bg='#101526',highlightthickness=0);canvas.pack(fill='x',pady=10); fields=ttk.Frame(body);fields.pack(anchor='w');ttk.Label(fields,text='Начало, сек').pack(side='left');start=tk.StringVar();ttk.Entry(fields,textvariable=start,width=10).pack(side='left',padx=6);ttk.Label(fields,text='Конец, сек').pack(side='left');end=tk.StringVar();ttk.Entry(fields,textvariable=end,width=10).pack(side='left',padx=6)
    status=ttk.Label(body,text='',wraplength=700);status.pack(anchor='w',pady=10);state={'index':0,'pcm':b'','duration':0,'playing':False}
    def fill():
        sidebar.delete(0,'end')
        for n,r in enumerate(rows): sidebar.insert('end',f"{n+1:02d}  {'✓' if r['status']=='confirmed' else '○'}  {r['phrase']}")
    def show(index):
        row=rows[index];pcm,duration=read_wav(a.archive,row['id']);state.update(index=index,pcm=pcm,duration=duration);start.set(row.get('wake_start_s',''));end.set(row.get('wake_end_s',''));heading.config(text=f"Образец {index+1}/{len(rows)} · {row['phrase']}");status.config(text=f"Длительность {duration:.2f} с · {'подтверждено' if row['status']=='confirmed' else 'нужна проверка'}")
        sidebar.selection_clear(0,'end');sidebar.selection_set(index);sidebar.see(index);canvas.delete('all');import array
        samples=array.array('h');samples.frombytes(pcm);width=max(1,canvas.winfo_width());height=200;step=max(1,len(samples)//width)
        for i in range(0,len(samples),step):
            chunk=samples[i:i+step];v=max((abs(x) for x in chunk),default=0)/32768;x=i/len(samples)*width;canvas.create_line(x,height/2-v*90,x,height/2+v*90,fill='#00dfff')
        draw_bounds()
    def draw_bounds(*_):
        canvas.delete("boundary")
        if state["duration"] <= 0: return
        try:
            for value,color in ((float(start.get()),"#00eaff"),(float(end.get()),"#bb79ff")):
                x=max(0,min(canvas.winfo_width(),value/state["duration"]*canvas.winfo_width()))
                canvas.create_line(x,0,x,200,fill=color,width=2,tags="boundary")
        except ValueError: pass
    start.trace_add("write",draw_bounds); end.trace_add("write",draw_bounds)
    def selected(_):
        if sidebar.curselection(): show(sidebar.curselection()[0])
    def play(segment):
        if state['playing']:return
        try:
            blob=clipped_wav(state['pcm'],float(start.get()),float(end.get())) if segment else clipped_wav(state['pcm'],0,state['duration'])
        except (ValueError,OverflowError):messagebox.showerror('Границы','Укажите корректные границы записи.');return
        state['playing']=True
        def run():
            try:winsound.PlaySound(blob,winsound.SND_MEMORY)
            finally:root.after(0,lambda:state.update(playing=False))
        threading.Thread(target=run,daemon=True).start()
    def confirm():
        try:
            begin,finish=float(start.get()),float(end.get());clipped_wav(state['pcm'],begin,finish)
            row=rows[state['index']];row.update(wake_start_s=f'{begin:.3f}',wake_end_s=f'{finish:.3f}',status='confirmed');save_review(a.reviewed,rows);fill();show(state['index']);status.config(text='Подтверждено и сохранено локально. Оригиналы не изменены.')
        except (ValueError,OSError,OverflowError) as error:messagebox.showerror('Не сохранено',str(error))
    controls=ttk.Frame(body);controls.pack(anchor='w',pady=10)
    for label,action in [('Вся запись',lambda:play(False)),('Выделенное слово',lambda:play(True)),('Подтвердить границы',confirm),('Следующая',lambda:show(min(len(rows)-1,state['index']+1)))]:ttk.Button(controls,text=label,command=action).pack(side='left',padx=4)
    ttk.Label(body,text='Сохраняются только явно подтверждённые вами границы. Файл хранится локально; записи в сеть не отправляются.',wraplength=700).pack(anchor='w')
    sidebar.bind('<<ListboxSelect>>',selected);fill();root.after(100,lambda:show(0));root.mainloop()

if __name__=='__main__': main()
