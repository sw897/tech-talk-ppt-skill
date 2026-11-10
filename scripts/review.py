"""Create a review page and contact sheet from actual PPTX exports and native notes."""
import argparse
import html
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
from PIL import Image, ImageDraw
from inspect_pptx import inspect, sha

def url(file, base):
    return quote(os.path.relpath(file,base).replace('\\','/'))

def review(args):
    report=inspect(args.pptx)
    if report['errors']:
        raise ValueError('PPTX structure has errors')
    receipt=json.loads((args.images/'render-receipt.json').read_text(encoding='utf8'))
    if receipt.get('source_sha256')!=report['sha256'] or not receipt.get('actual_pptx_export'):
        raise ValueError('Render receipt does not belong to the current PPTX')
    images=[]
    for i in range(1,report['slide_count']+1):
        p=args.images/f'{i:02}.png'
        if receipt['images'].get(p.name)!=sha(p.read_bytes()):
            raise ValueError('Rendered page hash differs: '+p.name)
        images.append(p)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    contact=args.output.with_name(args.output.stem+'_contact.png')
    rows=math.ceil(len(images)/2)
    sheet=Image.new('RGB',(1600,rows*480),'white');draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(images):
        with Image.open(p) as im:
            im=im.convert('RGB');im.thumbnail((776,437),Image.Resampling.LANCZOS)
            x=(i%2)*800+12;y=(i//2)*480+28
            sheet.paste(im,(x,y));draw.text((x,(i//2)*480+6),f'{i+1:02}',fill='#15344b')
    sheet.save(contact)
    title=html.escape(args.pptx.stem)
    body=[f'<h1>{title}</h1><p><a href="{url(args.pptx,args.output.parent)}">打开PPTX</a> · 实际导出：{html.escape(receipt["backend"])} · {len(images)}页</p>',
          '<p>图片来自当前PPTX实际静态导出。讲稿从原生备注读取；静态检查不证明放映、声音、投影或讲授计时。</p>',
          f'<details><summary>整套联系表</summary><img src="{url(contact,args.output.parent)}" alt="整套联系表"></details>',
          '<nav>'+''.join(f'<a href="#page-{i}">{i}</a>' for i in range(1,len(images)+1))+'</nav>']
    for s,p in zip(report['slides'],images):
        body.append(f'<section id="page-{s["index"]}"><h2>PPT第{s["index"]}页</h2><img src="{url(p,args.output.parent)}" alt="PPT第{s["index"]}页"><details><summary>完整讲稿</summary><div class="notes">{html.escape(s["notes"])}</div></details></section>')
    css='*{box-sizing:border-box}body{margin:0;background:#edf3f6;color:#19384e;font:17px/1.8 "Microsoft YaHei",sans-serif}main{max-width:1260px;margin:auto;background:white;padding:24px 32px}h1{font-size:28px}h2{font-size:23px}a{color:#006f86}img{display:block;max-width:100%;height:auto;border:1px solid #d3e1e9}nav{display:flex;gap:18px;flex-wrap:wrap;margin:20px 0}section{padding-top:20px;margin-top:24px;border-top:1px solid #cddde6;scroll-margin-top:10px}details{margin:14px 0}.notes{white-space:pre-wrap;padding:16px;background:#f1f7fa}summary{cursor:pointer}@media(max-width:700px){main{padding:16px}}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+css+'</style></head><body><main>'+''.join(body)+'</main></body></html>'
    args.output.write_text(page,encoding='utf8')
    print(json.dumps({'review':str(args.output.resolve()),'pages':len(images),'contact':str(contact.resolve()),'pptx_sha256':report['sha256']},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pptx',type=Path);p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    review(p.parse_args())
