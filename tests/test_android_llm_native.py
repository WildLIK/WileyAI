"""Production JNI lifetime/ABI tests with fake llama, not real GGUF inference."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
PINNED=ROOT/'local/android-native/llama.cpp-8642541b255bfb5dc39cd351a178be09013a55d6'

@pytest.fixture(scope='module')
def native_probe(tmp_path_factory):
    java=Path(os.environ.get('JAVA_HOME',''))
    compiler=os.environ.get('CXX') or shutil.which('clang++') or shutil.which('g++')
    build_env=os.environ.copy()
    if sys.platform=='win32':
        # Old PATH LLVM can be incompatible with a newer installed MSVC STL.
        # Use an already installed NDK compiler and an existing developer env;
        # do not install tools or modify the user's global environment.
        if not os.environ.get('CXX'):
            sdk=Path(os.environ.get('ANDROID_HOME',str(Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk')))
            candidates=list((sdk/'ndk').glob('*/toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'))
            if candidates:compiler=str(sorted(candidates,key=lambda p:tuple(int(v) for v in p.parents[5].name.split('.') if v.isdigit()))[-1])
        vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
        if vswhere.exists() and compiler and 'clang' in Path(compiler).name:
            found=subprocess.run([str(vswhere),'-latest','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],capture_output=True,text=True,timeout=10)
            setup=Path(found.stdout.strip())/'VC/Auxiliary/Build/vcvars64.bat'
            if setup.exists() and '"' not in str(setup):
                env_result=subprocess.run(f'cmd.exe /d /s /c ""{setup}" >nul && set"',capture_output=True,text=True,timeout=30)
                assert env_result.returncode==0,env_result.stderr
                for line in env_result.stdout.splitlines():
                    if '=' in line and not line.startswith('='):
                        key,value=line.split('=',1);build_env[key]=value
    if not compiler or not (java/'include/jni.h').exists() or not (PINNED/'include/llama.h').exists():pytest.skip('Host C++ compiler, JDK JNI headers and pinned source required')
    folder=tmp_path_factory.mktemp('android-c8-jni')
    suffix='wiley_llm.dll' if sys.platform=='win32' else 'libwiley_llm.so'
    includes=[java/'include',java/('include/win32' if sys.platform=='win32' else 'include/linux'),PINNED/'include',PINNED/'ggml/include']
    target=['--target=x86_64-pc-windows-msvc'] if sys.platform=='win32' and 'clang' in Path(compiler).name else []
    args=[compiler,*target,'-std=c++17','-shared','-O1',*(['-fPIC'] if sys.platform!='win32' else []),*[item for p in includes for item in ['-I',str(p)]],str(ROOT/'android/app/src/main/cpp/wiley_llm.cpp'),str(ROOT/'tests/android/fake_llama_c8.cpp'),'-o',str(folder/suffix)]
    result=subprocess.run(args,capture_output=True,text=True,timeout=90,env=build_env)
    assert result.returncode==0,result.stdout+result.stderr
    executable='javac.exe' if sys.platform=='win32' else 'javac'
    files=[ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile/LocalLlmNative.java',ROOT/'tests/android/C8NativeProbe.java']
    result=subprocess.run([str(java/'bin'/executable),'-encoding','UTF-8','-d',str(folder),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return java/'bin'/('java.exe' if sys.platform=='win32' else 'java'),folder

@pytest.mark.parametrize('scenario',['reuse','invalid','grammar-error','cancel-load','cancel-prefill','close-inflight'])
def test_native_lifetime(native_probe,scenario):
    java,folder=native_probe
    result=subprocess.run([str(java),'-Djava.library.path='+str(folder),'-cp',str(folder),'ru.wildlik.wileyai.mobile.C8NativeProbe',scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
