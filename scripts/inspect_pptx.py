"""Inspect static PPTX relationships, native objects, notes, media and canvas bounds."""
import argparse
import hashlib
import json
import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main', 'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def relationships(data, part):
    folder, name = posixpath.split(part)
    rel_part = posixpath.join(folder, '_rels', name + '.rels')
    if rel_part not in data:
        return {}
    return {e.get('Id'): dict(e.attrib) for e in ET.fromstring(data[rel_part])}

def resolve(part, target):
    return posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(part), target))

def ordered_slides(data):
    root = ET.fromstring(data['ppt/presentation.xml'])
    rels = relationships(data, 'ppt/presentation.xml')
    return [resolve('ppt/presentation.xml', rels[e.get('{' + NS['r'] + '}id')]['Target']) for e in root.findall('p:sldIdLst/p:sldId', NS)]

def notes_for(data, part):
    rels = relationships(data, part)
    links = [v for v in rels.values() if v.get('Type', '').endswith('/notesSlide')]
    if not links:
        return ''
    root = ET.fromstring(data[resolve(part, links[0]['Target'])])
    values = []
    for shape in root.findall('p:cSld/p:spTree/p:sp', NS):
        ph = shape.find('p:nvSpPr/p:nvPr/p:ph', NS)
        if ph is not None and ph.get('type') == 'body':
            values.extend(''.join(t.text or '' for t in p.findall('.//a:t', NS)) for p in shape.findall('p:txBody/a:p', NS))
    return '\n'.join(values).strip()

def object_name(element):
    n = element.find('.//p:cNvPr', NS)
    return n.get('name', '') if n is not None else ''

def inspect(file):
    with zipfile.ZipFile(file) as z:
        bad = z.testzip()
        if bad:
            raise ValueError('ZIP CRC error: ' + bad)
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate ZIP members')
        data = {n: z.read(n) for n in z.namelist()}
    errors, warnings = [], []
    ct = ET.fromstring(data['[Content_Types].xml'])
    for declaration in ct:
        if declaration.tag.endswith('Override'):
            target = declaration.get('PartName','').lstrip('/')
            if target not in data:
                errors.append({'error':'Content type declaration has no target','part':target})
    for name, blob in data.items():
        if name.endswith(('.xml', '.rels')):
            ET.fromstring(blob)
        if name.endswith('.rels'):
            if name == '_rels/.rels':
                owner = ''
            else:
                prefix, base = name.rsplit('/_rels/', 1)
                owner = prefix + '/' + base[:-5]
            for rel in ET.fromstring(blob):
                if rel.get('TargetMode') == 'External':
                    continue
                target = rel.get('Target', '')
                resolved = resolve(owner, target)
                if not target or resolved not in data:
                    errors.append({'part': name, 'relationship': rel.get('Id'), 'missing': resolved})
    root = ET.fromstring(data['ppt/presentation.xml'])
    size = root.find('p:sldSz', NS)
    cx, cy = int(size.get('cx')), int(size.get('cy'))
    result = []
    ids = set()
    for index, part in enumerate(ordered_slides(data), 1):
        s = ET.fromstring(data[part])
        ident = s.find('p:cSld', NS).get('name', '')
        if not ident or ident in ids:
            errors.append({'slide': index, 'error': 'Missing or duplicate stable slide id'})
        ids.add(ident)
        names, objects = set(), []
        for e in s.find('p:cSld/p:spTree', NS):
            if e.tag not in {f"{{{NS['p']}}}{kind}" for kind in ['sp', 'pic', 'graphicFrame', 'cxnSp']}:
                continue
            name = object_name(e)
            if not name or name in names:
                errors.append({'slide': index, 'error': 'Missing or duplicate object name', 'object': name})
            names.add(name)
            text = '\n'.join(''.join(t.text or '' for t in p.findall('.//a:t', NS)) for p in e.findall('.//a:p', NS))
            kind = 'table' if e.find('.//a:tbl', NS) is not None else ('image' if e.tag.endswith('pic') else 'shape')
            xfrm = e.find('.//a:xfrm', NS)
            if xfrm is None:
                xfrm = e.find('p:xfrm', NS)
            bounds = None
            if xfrm is not None:
                off, ext = xfrm.find('a:off', NS), xfrm.find('a:ext', NS)
                if off is not None and ext is not None:
                    x,y,w,h = int(off.get('x')),int(off.get('y')),int(ext.get('cx')),int(ext.get('cy'))
                    bounds = [x,y,w,h]
                    if x < -10 or y < -10 or x + w > cx + 10 or y + h > cy + 10:
                        errors.append({'slide': index, 'object': name, 'error': 'Canvas overflow', 'bounds': bounds})
            objects.append({'name': name, 'kind': kind, 'text': text, 'bounds_emu': bounds})
        notes = notes_for(data, part)
        if not notes:
            errors.append({'slide': index, 'error': 'Missing speaker notes'})
        result.append({'index': index, 'id': ident, 'part': part, 'notes': notes, 'objects': objects,
                       'native_text': '\n'.join(x['text'] for x in objects if x['text']),
                       'tables': sum(o['kind']=='table' for o in objects), 'images': sum(o['kind']=='image' for o in objects)})
    fonts = sorted({n.get('typeface') for p,b in data.items() if p.startswith('ppt/') and p.endswith('.xml') for n in ET.fromstring(b).iter() if n.tag in {f"{{{NS['a']}}}{k}" for k in ['latin','ea','cs']} and n.get('typeface')})
    return {'file': str(Path(file).resolve()), 'sha256': sha(Path(file).read_bytes()), 'slide_count': len(result), 'canvas_emu':[cx,cy], 'fonts': fonts,
            'slides': result, 'media': {n:sha(b) for n,b in data.items() if n.startswith('ppt/media/')}, 'errors':errors, 'warnings':warnings,
            'limits':'Structure and canvas bounds only; no text fit, semantic, visual, slideshow or sound claim.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pptx', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = inspect(args.pptx)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'slides':report['slide_count'], 'media':len(report['media']), 'errors':report['errors'], 'fonts':report['fonts']}, ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
