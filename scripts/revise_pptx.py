"""Apply guarded text or image changes to named static objects and update the adopted spec."""
import argparse
import copy
import json
import os
import posixpath
import struct
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from inspect_pptx import NS, sha, ordered_slides, relationships, resolve, object_name, inspect, notes_for

for prefix in ['p', 'a', 'r']:
    ET.register_namespace(prefix, NS[prefix])
ET.register_namespace('rel', NS['rel'])
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
ET.register_namespace('ct', CT)

def xml(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)

def image_size(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return struct.unpack('>II', data[16:24])
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data):
            if data[i] != 255:
                i += 1; continue
            marker = data[i+1]; i += 2
            if marker in [0xD8,0xD9]:
                continue
            n = int.from_bytes(data[i:i+2], 'big')
            if marker in [0xC0,0xC1,0xC2,0xC3]:
                h,w = struct.unpack('>HH', data[i+3:i+7]); return w,h
            i += n
    raise ValueError('Only readable PNG/JPEG images are supported')

def update_spec(spec, op, change_dir):
    matches = [s for s in spec['slides'] if s['id'] == op['slide']]
    if len(matches) != 1:
        raise ValueError('Spec slide does not match change')
    slide = matches[0]
    if op['op'] == 'replace_notes_text':
        if slide['notes'].count(op['old']) != 1:
            raise ValueError('Spec notes guard must match one occurrence')
        slide['notes'] = slide['notes'].replace(op['old'], op['new'], 1)
    elif op['op'] == 'replace_text':
        if op['object'] == 'title':
            if slide.get('title') != op['old']:
                raise ValueError('Spec title guard failed')
            slide['title'] = op['new']; return
        objects = [e for e in slide.get('elements', []) if e['id'] == op['object']]
        if len(objects) != 1:
            raise ValueError('Spec object not found')
        e = objects[0]
        if e['type'] == 'text':
            if e['text'] != op['old']:
                raise ValueError('Spec text guard failed')
            e['text'] = op['new']
        elif e['type'] == 'table':
            cells = [(i,j) for i,row in enumerate(e['rows']) for j,v in enumerate(row) if str(v) == op['old']]
            if len(cells) != 1:
                raise ValueError('Spec table guard must match one cell')
            i,j = cells[0]; e['rows'][i][j] = op['new']
        else:
            raise ValueError('Spec object is not text/table')
    else:
        value = {'path': str((change_dir / op['path']).resolve()), 'sha256': op['sha256'], 'kind': op.get('kind', 'unspecified')}
        if op['object'] == 'full-slide' and spec['mode'] == 'image':
            slide['image'] = value
        else:
            matches = [e for e in slide.get('elements', []) if e['id'] == op['object'] and e['type'] == 'image']
            if len(matches) != 1:
                raise ValueError('Spec image not found')
            matches[0].update(value)

def rebase_spec(spec, before, after):
    if spec.get('source'):
        spec['source']['path'] = os.path.relpath((before / spec['source']['path']).resolve(), after).replace('\\','/')
    for s in spec['slides']:
        if s.get('image'):
            if isinstance(s['image'], str):
                s['image'] = {'path':s['image']}
            v = s['image']; v['path'] = os.path.relpath((before / v['path']).resolve(), after).replace('\\','/')
        for e in s.get('elements', []):
            if e['type'] == 'image':
                e['path'] = os.path.relpath((before / e['path']).resolve(), after).replace('\\','/')

def revise(args):
    outputs = [args.output, args.updated_spec, args.receipt]
    if len(set(p.resolve() for p in outputs)) != len(outputs) or any(p.exists() for p in outputs):
        raise ValueError('Outputs must be distinct new files')
    source = args.input.read_bytes()
    change = json.loads(args.change.read_text(encoding='utf-8-sig'))
    if change.get('expected_pptx_sha256') and sha(source) != change['expected_pptx_sha256']:
        raise ValueError('PPTX source hash guard failed')
    if not isinstance(change.get('operations'), list) or not change['operations']:
        raise ValueError('Nonempty operations required')
    spec = json.loads(args.spec.read_text(encoding='utf-8-sig'))
    with zipfile.ZipFile(args.input) as z:
        if z.testzip():
            raise ValueError('Source CRC error')
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate source ZIP member')
        original = {n:z.read(n) for n in z.namelist()}
        infos, comment = z.infolist(), z.comment
    data = original.copy()
    slides = {}
    for part in ordered_slides(data):
        ident = ET.fromstring(data[part]).find('p:cSld', NS).get('name')
        if not ident or ident in slides:
            raise ValueError('Missing or duplicate slide id')
        slides[ident] = part
    touched = []
    note_targets = set()
    for op in change['operations']:
        if op.get('op') not in ['replace_text','replace_image','replace_notes_text'] or op.get('slide') not in slides:
            raise ValueError('Unknown operation or slide')
        part = slides[op['slide']]; root = ET.fromstring(data[part])
        if op['op'] == 'replace_notes_text':
            if not isinstance(op.get('old'), str) or not op['old'] or not isinstance(op.get('new'), str) or op['old'] == op['new']:
                raise ValueError('Different nonempty notes old/new strings required')
            if notes_for(data, part).count(op['old']) != 1:
                raise ValueError('Notes guard must match one occurrence')
            links = [v for v in relationships(data, part).values() if v.get('Type','').endswith('/notesSlide')]
            if len(links) != 1:
                raise ValueError('Exactly one native notes part required')
            note_part = resolve(part, links[0]['Target'])
            note_root = ET.fromstring(data[note_part])
            nodes = []
            for shape in note_root.findall('p:cSld/p:spTree/p:sp', NS):
                ph = shape.find('p:nvSpPr/p:nvPr/p:ph', NS)
                if ph is not None and ph.get('type') == 'body':
                    nodes.extend(t for t in shape.findall('.//a:t', NS) if op['old'] in (t.text or ''))
            if len(nodes) != 1 or nodes[0].text.count(op['old']) != 1:
                raise ValueError('Notes text crosses runs or is ambiguous; use authoring')
            nodes[0].text = nodes[0].text.replace(op['old'], op['new'], 1)
            data[note_part] = xml(note_root)
            note_targets.add(note_part)
            update_spec(spec,op,args.change.parent)
            touched.append({'slide':op['slide'],'object':'notes','operation':op['op']})
            continue
        matches = [e for e in root.find('p:cSld/p:spTree', NS) if object_name(e) == op.get('object')]
        if len(matches) != 1:
            raise ValueError('Object name must match exactly one object')
        element = matches[0]
        if op['op'] == 'replace_text':
            if not isinstance(op.get('old'), str) or not isinstance(op.get('new'), str) or op['old'] == op['new']:
                raise ValueError('Different old/new strings required')
            if op['object'] in ['page','footer']:
                raise ValueError('Use a coherent deck-level rebuild for page/footer changes')
            nodes = [t for t in element.findall('.//a:t', NS) if t.text == op['old']]
            if len(nodes) != 1:
                raise ValueError('Text guard must match one complete run; split or ambiguous text needs authoring')
            nodes[0].text = op['new']
        else:
            image = (args.change.parent / op['path']).resolve()
            blob = image.read_bytes()
            if not op.get('sha256') or sha(blob) != op['sha256']:
                raise ValueError('Replacement image hash guard failed')
            extension = image.suffix.lower()
            if extension not in ['.png','.jpg','.jpeg']:
                raise ValueError('PNG/JPEG replacement required')
            blip = element.find('.//a:blip', NS)
            if blip is None:
                raise ValueError('Target is not an embedded picture')
            relpart = posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
            relroot = ET.fromstring(data[relpart]); relmap = relationships(data,part)
            old_rid = blip.get('{' + NS['r'] + '}embed')
            if old_rid not in relmap:
                raise ValueError('Old image relationship missing')
            oldpart = resolve(part,relmap[old_rid]['Target'])
            old_size,new_size = image_size(data[oldpart]),image_size(blob)
            if abs(old_size[0]/old_size[1]-new_size[0]/new_size[1]) > 0.01:
                raise ValueError('Replacement aspect ratio differs; author the layout explicitly')
            target = 'ppt/media/cws_'+op['sha256']+extension
            rid = 'rIdCws'+op['sha256'][:16]
            existing = next((r for r in relroot if r.get('Id')==rid),None)
            if existing is not None:
                if resolve(part,existing.get('Target')) != target:
                    raise ValueError('Relationship id collision')
            else:
                ET.SubElement(relroot,'{' + NS['rel'] + '}Relationship',Id=rid,Type=NS['r']+'/image',Target='/'+target)
            data[target] = blob
            blip.set('{' + NS['r'] + '}embed',rid)
            data[relpart] = xml(relroot)
            ct = ET.fromstring(data['[Content_Types].xml'])
            ext = extension[1:]
            if not any(e.get('Extension') == ext for e in ct):
                ET.SubElement(ct,'{' + CT + '}Default',Extension=ext,ContentType='image/png' if ext=='png' else 'image/jpeg')
                data['[Content_Types].xml'] = xml(ct)
        data[part] = xml(root)
        update_spec(spec,op,args.change.parent)
        touched.append({'slide':op['slide'],'object':op['object'],'operation':op['op']})
    rebase_spec(spec,args.spec.parent,args.updated_spec.parent)
    changed = sorted(n for n in original if original[n] != data[n])
    added = sorted(set(data)-set(original))
    expected = {slides[op['slide']] for op in change['operations'] if op['op'] != 'replace_notes_text'} | note_targets
    for op in change['operations']:
        if op['op']=='replace_image':
            p=slides[op['slide']];expected.add(posixpath.join(posixpath.dirname(p),'_rels',posixpath.basename(p)+'.rels'))
    if '[Content_Types].xml' in changed:
        expected.add('[Content_Types].xml')
    if set(changed)-expected:
        raise ValueError('Unexpected package change')
    for p in outputs:
        p.parent.mkdir(parents=True,exist_ok=True)
    # All operations and spec guards have passed before the first output is written.
    with tempfile.TemporaryDirectory(prefix='.cws-revision-',dir=args.output.parent) as scratch:
        candidate=Path(scratch)/'candidate.pptx'
        with zipfile.ZipFile(candidate,'x',zipfile.ZIP_DEFLATED) as z:
            z.comment=comment
            for info in infos:
                z.writestr(info,data[info.filename])
            for name in added:
                z.writestr(name,data[name])
        report=inspect(candidate)
        if report['errors']:
            raise ValueError('Revised package failed inspection: '+str(report['errors']))
        with args.output.open('xb') as f:
            f.write(candidate.read_bytes())
    args.updated_spec.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    receipt={'source_sha256':sha(source),'output_sha256':sha(args.output.read_bytes()),'operations':touched,
             'changed_existing_parts':changed,'added_parts':added,'unchanged_parts':len(original)-len(changed),
             'unchanged_media':sum(n.startswith('ppt/media/') and original[n]==data[n] for n in original),
             'all_notes_byte_identical':all(original[n]==data[n] for n in original if n.startswith('ppt/notesSlides/')),
             'changed_notes_parts':sorted(n for n in changed if n.startswith('ppt/notesSlides/')),
             'unaffected_notes_byte_identical':all(original[n]==data[n] for n in original if n.startswith('ppt/notesSlides/') and n not in note_targets),
             'image_generation_calls_by_revision_tool':0,'inspection_errors':report['errors']}
    args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['input','change','output','spec','updated-spec','receipt']:
        parser.add_argument('--'+key,type=Path,required=True)
    revise(parser.parse_args())
