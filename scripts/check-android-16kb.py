"""Inspect every packaged native ELF LOAD segment and APK alignment with Android SDK tools."""
import argparse, os, pathlib, subprocess, tempfile, zipfile

def main():
    p=argparse.ArgumentParser();p.add_argument('apk',type=pathlib.Path);p.add_argument('--sdk',type=pathlib.Path,default=pathlib.Path(os.environ.get('ANDROID_HOME',str(pathlib.Path(os.environ['LOCALAPPDATA'])/'Android/Sdk'))));a=p.parse_args()
    ndk=a.sdk/'ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-readelf.exe'
    align=a.sdk/'build-tools/36.0.0/zipalign.exe';failed=False;count=0
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(a.apk) as z:
        for info in z.infolist():
            if not info.filename.startswith('lib/') or not info.filename.endswith('.so'): continue
            count+=1; path=pathlib.Path(tmp)/('lib'+str(count)+'.so');path.write_bytes(z.read(info));proc=subprocess.run([str(ndk),'-lW',str(path)],capture_output=True,text=True,check=True)
            loads=[s.split() for s in proc.stdout.splitlines() if s.strip().startswith('LOAD')];segments=[int(s[-1],16) for s in loads];ok=bool(segments) and all(n>=16384 and n%16384==0 and (int(s[1],16)-int(s[2],16))%16384==0 for s,n in zip(loads,segments));failed |= not ok
            print(info.filename, ' '.join(hex(n) for n in segments), 'OK' if ok else 'FAIL')
    if count==0: raise SystemExit('No native libraries in APK')
    result=subprocess.run([str(align),'-c','-P','16','4',str(a.apk)])
    if failed or result.returncode: raise SystemExit(1)
    print('All',count,'native libraries have 16-KiB LOAD alignment; zipalign passed.')
if __name__=='__main__':main()
