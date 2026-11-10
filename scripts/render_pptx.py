"""Export actual PPTX pages through WPS/PowerPoint COM or LibreOffice and Poppler."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from inspect_pptx import sha, inspect

def run(argv,timeout=180):
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    p=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8-sig',errors='replace',timeout=timeout,creationflags=flags)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Renderer failed')
    return p.stdout.strip()

def render(args):
    src=args.pptx.resolve();dest=args.output_dir.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError('Render directory must be new or empty')
    checked=inspect(src)
    if checked['errors']:
        raise ValueError('Input package has structural errors')
    dest.mkdir(parents=True,exist_ok=True)
    backend=args.backend
    attempts=[]
    if backend=='auto':
        candidates=['wps','powerpoint'] if os.name=='nt' else ['libreoffice']
    else:
        candidates=[backend]
    result=None
    for backend in candidates:
        try:
            if backend in ['wps','powerpoint']:
                if os.name!='nt':
                    raise RuntimeError('COM renderer requires Windows')
                raw=run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('render_windows.ps1')),
                         '-InputPath',str(src),'-OutputDir',str(dest),'-Backend',backend,'-Width',str(args.width),'-Height',str(args.height)])
                result=json.loads(raw.splitlines()[-1])
            else:
                soffice=args.soffice or shutil.which('soffice')
                poppler=args.pdftoppm or shutil.which('pdftoppm')
                if not soffice or not poppler:
                    raise RuntimeError('LibreOffice and pdftoppm are required')
                with tempfile.TemporaryDirectory(prefix='tech-talk-ppt-render-') as scratch:
                    tmp=Path(scratch);profile=(tmp/'profile').as_uri()
                    run([soffice,'-env:UserInstallation='+profile,'--headless','--convert-to','pdf','--outdir',str(tmp),str(src)])
                    pdf=tmp/(src.stem+'.pdf')
                    if not pdf.is_file():
                        raise RuntimeError('LibreOffice did not export a PDF')
                    run([poppler,'-png','-scale-to-x',str(args.width),'-scale-to-y',str(args.height),str(pdf),str(tmp/'page')])
                    pages=sorted(tmp.glob('page-*.png'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
                    for i,p in enumerate(pages,1):
                        shutil.copyfile(p,dest/f'{i:02}.png')
                    result={'backend':'libreoffice+pdftoppm','slides':len(pages),'width':args.width,'height':args.height}
            break
        except Exception as error:
            attempts.append({'backend':backend,'error':str(error)})
            # A partially rendered deck is preserved for diagnosis; do not mix backends.
            if list(dest.glob('*.png')):
                break
    if result is None:
        (dest/'render-error.json').write_text(json.dumps(attempts,ensure_ascii=False,indent=2),encoding='utf8')
        raise RuntimeError('No renderer completed: '+json.dumps(attempts,ensure_ascii=False))
    images=sorted(dest.glob('*.png'))
    if len(images)!=checked['slide_count'] or result['slides']!=checked['slide_count']:
        raise ValueError('Rendered page count differs from PPTX')
    result.update({'source_sha256':sha(src.read_bytes()),'actual_pptx_export':True,'images':{p.name:sha(p.read_bytes()) for p in images},
                   'prior_attempts':attempts,'slideshow_or_sound_verified':False})
    (dest/'render-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'backend':result['backend'],'slides':result['slides'],'output_dir':str(dest)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pptx',type=Path);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--backend',choices=['auto','wps','powerpoint','libreoffice'],default='auto');p.add_argument('--width',type=int,default=1600);p.add_argument('--height',type=int,default=900)
    p.add_argument('--soffice');p.add_argument('--pdftoppm');args=p.parse_args()
    if args.width<=0 or args.height<=0:
        p.error('Positive render dimensions required')
    render(args)
