#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import PptxGenJS from 'pptxgenjs';
import JSZip from 'jszip';

const hash = b => createHash('sha256').update(b).digest('hex');
const fail = message => { throw new Error(message); };
const argv = process.argv.slice(2), args = {};
if (argv.includes('--help')) {
  console.log('node build_pptx.mjs --spec deck.json --output deck.pptx'); process.exit(0);
}
for (let i = 0; i < argv.length; i += 2) {
  if (!['--spec', '--output'].includes(argv[i]) || !argv[i + 1]) fail('Unknown or incomplete argument');
  if (args[argv[i]]) fail('Repeated argument'); args[argv[i]] = argv[i + 1];
}
if (!args['--spec'] || !args['--output']) fail('--spec and --output are required');
const specFile = path.resolve(args['--spec']), output = path.resolve(args['--output']);
for (const target of [output, output + '.build.json']) {
  await fs.access(target).then(() => fail('Output already exists')).catch(e => { if (e.code !== 'ENOENT') throw e; });
}
const sourceBytes = await fs.readFile(specFile), spec = JSON.parse(sourceBytes.toString('utf8'));
if (spec.source) {
  const input = await fs.readFile(path.resolve(path.dirname(specFile), spec.source.path));
  if (!spec.source.sha256 || hash(input) !== spec.source.sha256) fail('Adopted source has changed; reconcile the storyboard before building');
}
if (spec.schema_version !== 1 || !['image', 'hybrid'].includes(spec.mode)) fail('Unsupported schema_version or mode');
if (!Array.isArray(spec.slides) || !spec.slides.length) fail('slides must be a nonempty array');
const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const packageVersion = JSON.parse(await fs.readFile(path.join(skillRoot, 'package.json'), 'utf8')).version;
const theme = { ...JSON.parse(await fs.readFile(path.join(skillRoot, 'assets/styles/tech-blue/theme.json'), 'utf8')), ...(spec.theme || {}) };
const canvas = spec.canvas || theme.canvas;
for (const v of [canvas.width, canvas.height]) if (!Number.isFinite(v) || v <= 0) fail('Invalid canvas');
const inch = v => v / 96, pt = v => v * 0.75;
const color = value => String(value || theme.ink).replace(/^#/, '');
const receipts = [], assets = [], ids = new Set();
function box(v, label) {
  if (!Array.isArray(v) || v.length !== 4 || v.some(x => !Number.isFinite(x)) || v[2] <= 0 || v[3] <= 0) fail('Invalid box: ' + label);
  if (v[0] < 0 || v[1] < 0 || v[0] + v[2] > canvas.width + 0.01 || v[1] + v[3] > canvas.height + 0.01) fail('Box outside canvas: ' + label);
  return { x: inch(v[0]), y: inch(v[1]), w: inch(v[2]), h: inch(v[3]) };
}
async function asset(value, label) {
  const def = typeof value === 'string' ? { path: value } : value;
  if (!def?.path || /^https?:/i.test(def.path)) fail('Local asset required: ' + label);
  const file = path.resolve(path.dirname(specFile), def.path), b = await fs.readFile(file), sha256 = hash(b);
  if (def.sha256 && sha256 !== def.sha256) fail('Asset hash mismatch: ' + label);
  if (!['.png', '.jpg', '.jpeg'].includes(path.extname(file).toLowerCase())) fail('Images must be PNG or JPEG');
  assets.push({ slide: label, path: path.relative(path.dirname(specFile), file).replaceAll('\\', '/'), sha256, bytes: b.length, kind: def.kind || 'unspecified' });
  return file;
}
const pptx = new PptxGenJS();
pptx.defineLayout({ name: 'CUSTOM', width: inch(canvas.width), height: inch(canvas.height) });
pptx.layout = 'CUSTOM'; pptx.author = spec.author || 'TechTalk PPT'; pptx.subject = spec.subject || '';
pptx.title = spec.title || 'Presentation'; pptx.company = ''; pptx.lang = 'zh-CN';
pptx.theme = { headFontFace: theme.font, bodyFontFace: theme.font, lang: 'zh-CN' };
function text(slide, id, value, rect, extra = {}) {
  slide.addText(String(value), { ...box(rect, id), objectName: id, fontFace: theme.font, fontSize: pt(theme.bodySize), color: color(theme.ink),
    margin: 0, breakLine: false, valign: 'mid', paraSpaceAfterPt: 0, ...extra });
}
for (let index = 0; index < spec.slides.length; index++) {
  const s = spec.slides[index];
  if (!/^[a-zA-Z0-9_-]+$/.test(s.id || '') || ids.has(s.id)) fail('Missing, invalid or duplicate slide id'); ids.add(s.id);
  if (typeof s.notes !== 'string' || !s.notes.trim()) fail('Each slide requires notes: ' + s.id);
  const slide = pptx.addSlide(); slide.background = { color: color(theme.background) };
  const names = new Set(['title', 'footer', 'page', 'title-rule', 'footer-rule']);
  if (spec.mode === 'image') {
    if (s.elements?.length) fail('image mode cannot include native body elements');
    const img = await asset(s.image, s.id);
    slide.addImage({ path: img, objectName: 'full-slide', x: 0, y: 0, w: inch(canvas.width), h: inch(canvas.height), sizing: { type: 'contain', w: inch(canvas.width), h: inch(canvas.height) } });
  } else {
    if (typeof s.title !== 'string') fail('Hybrid slide requires title');
    for (const e of s.elements || []) {
      if (!/^[a-zA-Z0-9_-]+$/.test(e.id || '') || names.has(e.id)) fail('Invalid or duplicate object id: ' + s.id + '/' + e.id); names.add(e.id);
      if (e.type === 'text') {
        const size = e.fontSize ?? theme.bodySize;
        if (!Number.isFinite(size) || size <= 0) fail('Invalid fontSize');
        text(slide, e.id, e.text, e.box, { fontSize: pt(size), color: color(e.color), bold: !!e.bold, align: e.align || 'left', valign: e.valign || 'mid', ...(e.font ? { fontFace: e.font } : {}) });
      } else if (e.type === 'image') {
        const file = await asset(e, s.id + '/' + e.id), b = box(e.box, e.id);
        if (e.fit && !['contain', 'cover'].includes(e.fit)) fail('Unsupported image fit');
        slide.addImage({ path: file, objectName: e.id, ...b, sizing: { type: e.fit === 'cover' ? 'cover' : 'contain', w: b.w, h: b.h } });
      } else if (e.type === 'shape') {
        if (!['rect', 'roundRect', 'ellipse'].includes(e.shape || 'rect')) fail('Unsupported native shape');
        slide.addShape(pptx.ShapeType[e.shape || 'rect'], { ...box(e.box, e.id), objectName: e.id,
          fill: e.fill ? { color: color(e.fill) } : { color: theme.background, transparency: 100 },
          line: { color: color(e.color || theme.line), width: e.lineWidth ?? 1 } });
      } else if (e.type === 'line') {
        const points = [...(e.from || []), ...(e.to || [])];
        if (points.length !== 4 || points.some(x => !Number.isFinite(x))) fail('Invalid line points');
        const [x1, y1] = e.from, [x2, y2] = e.to;
        if ([x1,x2].some(x => x < 0 || x > canvas.width) || [y1,y2].some(y => y < 0 || y > canvas.height)) fail('Line outside canvas');
        slide.addShape(pptx.ShapeType.line, { x: inch(Math.min(x1,x2)), y: inch(Math.min(y1,y2)), w: inch(Math.abs(x2-x1)), h: inch(Math.abs(y2-y1)), flipH: x2 < x1, flipV: y2 < y1, objectName: e.id,
          line: { color: color(e.color || theme.blue), width: e.width ?? 2, ...(e.dash ? { dashType: 'dash' } : {}), ...(e.arrow ? { endArrowType: 'triangle' } : {}), ...(e.beginArrow ? { beginArrowType: 'triangle' } : {}) } });
      } else if (e.type === 'table') {
        if (!Array.isArray(e.rows) || !e.rows.length || !e.rows.every(r => Array.isArray(r) && r.length === e.rows[0].length)) fail('Rectangular table rows required');
        const b = box(e.box, e.id), cols = e.columnWidths || Array(e.rows[0].length).fill(e.box[2] / e.rows[0].length);
        if (cols.length !== e.rows[0].length || cols.some(v => !Number.isFinite(v) || v <= 0) || Math.abs(cols.reduce((a,v)=>a+v,0)-e.box[2]) > 1) fail('Invalid table column widths');
        const rows = e.rows.map((row, i) => row.map((v, j) => {
          const style = { ...(i > 0 ? e.columnStyles?.[j] : {}), ...(e.cellStyles?.[`${i},${j}`] || {}) };
          if (style.fontSize !== undefined && (!Number.isFinite(style.fontSize) || style.fontSize <= 0)) fail('Invalid cell fontSize');
          return { text: String(v), options: { bold: i === 0, fill: i === 0 ? color(e.headerFill || 'E8F1F4') : color(e.bodyFill || theme.background),
            ...(style.fontSize ? { fontSize: pt(style.fontSize) } : {}), ...(style.color ? { color: color(style.color) } : {}), ...(style.bold !== undefined ? { bold: !!style.bold } : {}) } };
        }));
        slide.addTable(rows, { ...b, objectName: e.id, colW: cols.map(inch), rowH: inch(e.rowHeight || e.box[3] / e.rows.length),
          fontFace: theme.font, fontSize: pt(e.fontSize || 26), color: theme.ink, border: { type: 'solid', color: theme.line, pt: 0.75 }, margin: pt(10), valign: 'mid', autoPage: false });
      } else fail('Unsupported element type: ' + e.type);
    }
    // Keep native chrome above full-canvas generated artwork. Cover typography
    // can use an explicit area instead of becoming raster text in the artwork.
    const titleStyle = s.titleStyle || {};
    const titleSize = titleStyle.fontSize ?? theme.titleSize;
    if (!Number.isFinite(titleSize) || titleSize <= 0) fail('Invalid title fontSize');
    text(slide, 'title', s.title, titleStyle.box || [56, 31, canvas.width - 112, 66], { fontSize: pt(titleSize), bold: true });
    if (titleStyle.rule !== false) slide.addShape(pptx.ShapeType.line, { x: inch(56), y: inch(111), w: inch(80), h: 0, objectName: 'title-rule', line: { color: theme.blue, width: 2 } });
    if (s.showFooter !== false) {
      if (s.footerRule !== false) slide.addShape(pptx.ShapeType.line, { x: inch(56), y: inch(canvas.height - 45), w: inch(canvas.width - 112), h: 0, objectName: 'footer-rule', line: { color: theme.line, width: 0.7 } });
      text(slide, 'footer', spec.footer || spec.title || '', [56, canvas.height - 35, canvas.width - 290, 24], { fontSize: pt(theme.footerSize), color: theme.muted });
      text(slide, 'page', `${index + 1} / ${spec.slides.length}`, [canvas.width - 200, canvas.height - 35, 144, 24], { fontSize: pt(theme.footerSize), color: theme.muted, align: 'right' });
    }
  }
  slide.addNotes(s.notes);
  receipts.push({ index: index + 1, id: s.id, title: s.title, elements: spec.mode === 'image' ? ['full-slide'] : [...names], notes_sha256: hash(Buffer.from(s.notes)) });
}
const data = await pptx.write({ outputType: 'nodebuffer', compression: true });
const zip = await JSZip.loadAsync(data);
// PptxGenJS 4.0.1 can declare one slideMaster override per slide while emitting
// only the shared master. Remove declarations without backing package parts;
// retain the actual shared master and let the independent inspector check rels.
const removedContentTypes = [];
const ctText = await zip.file('[Content_Types].xml').async('string');
zip.file('[Content_Types].xml', ctText.replace(/<Override\b[^>]*\/>/g, tag => {
  const part = tag.match(/\bPartName="([^"]+)"/)?.[1]?.replace(/^\//, '');
  if (part && !zip.file(part)) { removedContentTypes.push(part); return ''; }
  return tag;
}));
for (let i=0;i<spec.slides.length;i++) {
  const part = `ppt/slides/slide${i+1}.xml`, xml = await zip.file(part).async('string');
  const patched = xml.replace(/<p:cSld(?:\s+[^>]*)?>/, `<p:cSld name="${spec.slides[i].id}">`);
  if (xml === patched && !xml.includes(`name="${spec.slides[i].id}"`)) fail('Unable to write stable slide id');
  zip.file(part, patched);
}
const result = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
await fs.mkdir(path.dirname(output), { recursive: true });
const handle = await fs.open(output, 'wx'); try { await handle.writeFile(result); } finally { await handle.close(); }
const receipt = { version: packageVersion, mode: spec.mode, slides: receipts, assets, source_sha256: hash(sourceBytes), pptx_sha256: hash(result),
  runtime: { node: process.version, pptxgenjs: '4.0.1', jszip: '3.10.1' }, removed_unbacked_content_type_declarations: removedContentTypes, generated_images_by_this_script: 0, canvas };
await fs.writeFile(output + '.build.json', JSON.stringify(receipt, null, 2), { flag: 'wx' });
console.log(JSON.stringify({ output, mode: spec.mode, slides: receipts.length, bytes: result.length, sha256: receipt.pptx_sha256 }));
