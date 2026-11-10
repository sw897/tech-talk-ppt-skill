"""Export a self-contained local Skill ZIP with deterministic paths and byte checks."""
import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote,urlsplit

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=json.loads((ROOT/'package.json').read_text(encoding='utf8'))
VERSION=PACKAGE['version']
NAME=PACKAGE['name']
if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',NAME) or ROOT.name!=NAME:
    raise ValueError('Package name must match the Skill directory')
STEM=NAME+'_V'+VERSION
SKIP={'node_modules','.venv','venv','__pycache__','.git','outputs','dist','artifacts','.local'}
ALLOWED={'.md','.mjs','.py','.ps1','.json','.yaml','.yml','.txt','.png','.jpg','.jpeg','.gitignore',''}

def digest(b):
    return hashlib.sha256(b).hexdigest()

def export(dest):
    for suffix in ['.zip','.skill','_export.json']:
        if (dest/(STEM+suffix)).exists():
            raise ValueError('Release destination already contains an output')
    entry=(ROOT/'SKILL.md').read_text(encoding='utf8')
    if not re.search(r'^name: '+re.escape(NAME)+r'$',entry,re.M):
        raise ValueError('Skill name does not match release directory')
    files=[]
    for p in sorted(ROOT.rglob('*')):
        rel=p.relative_to(ROOT)
        if any(part in SKIP for part in rel.parts):
            continue
        if p.is_symlink():
            raise ValueError('Links are not distributable: '+str(rel))
        if not p.is_file():
            continue
        if p.name.startswith('.env') or p.suffix.lower() in ['.pptx','.zip','.skill','.pyc']:
            continue
        if p.suffix.lower() not in ALLOWED or p.stat().st_size>40*1024*1024:
            raise ValueError('Unexpected file: '+str(rel))
        if p.suffix in ['.md','.json','.mjs','.py','.ps1','.yaml','.txt']:
            text=p.read_text(encoding='utf-8-sig')
            if re.search(r'\b[A-Za-z]:[\\/]',text):
                raise ValueError('Machine-specific path in release: '+str(rel))
        files.append(p)
    for p in files:
        if p.suffix!='.md':
            continue
        text=p.read_text(encoding='utf8')
        for link in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)\)',text):
            parsed=urlsplit(link)
            if parsed.scheme or not parsed.path:
                continue
            target=(p.parent/unquote(parsed.path)).resolve()
            if not target.is_relative_to(ROOT) or target not in files:
                raise ValueError('Missing or external package reference: '+str(p.relative_to(ROOT))+' '+link)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in files:
            info=zipfile.ZipInfo(NAME+'/'+p.relative_to(ROOT).as_posix(),date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,p.read_bytes())
    blob=buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        if z.testzip():
            raise ValueError('Release CRC error')
        for p in files:
            if z.read(NAME+'/'+p.relative_to(ROOT).as_posix())!=p.read_bytes():
                raise ValueError('Release member changed')
    dest.mkdir(parents=True,exist_ok=True)
    outputs=[]
    for suffix in ['.zip','.skill']:
        p=dest/(STEM+suffix)
        with p.open('xb') as f:
            f.write(blob)
        outputs.append(str(p.resolve()))
    report={'name':NAME,'version':VERSION,'files':len(files),'bytes':len(blob),'sha256':digest(blob),'self_contained':True,'crc_and_members_verified':True,
            'installed':False,'published':False,'outputs':outputs,
            'members':{p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in files}}
    with (dest/(STEM+'_export.json')).open('x',encoding='utf8') as f:
        f.write(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='members'},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);export(p.parse_args().output_dir)
