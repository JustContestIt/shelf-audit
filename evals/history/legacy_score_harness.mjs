// Скоринг ответа против gt: node score.mjs runs/exp1_gpt-5.6-sol_r1_data.json gt_IMG_0643.json
// Пайплайн обработки боксов = копия «Парсинга» v7.1-slivers (валидация → IoU-дедуп →
// фильтр щепок → группировка); дальше позиционное сравнение слева направо по полкам.
import fs from 'node:fs';

const [dataFile, gtFile = 'gt_IMG_0643.json'] = process.argv.slice(2);
const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const gt = JSON.parse(fs.readFileSync(gtFile, 'utf8'));

const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
const boxesIn = Array.isArray(data.boxes) ? data.boxes : [];

// 1) валидация координат — как в «Парсинге»
const valid = [];
let bad = 0;
for (const b of boxesIn) {
  const c = b && b.box_2d;
  if (!Array.isArray(c) || c.length !== 4 || c.some(v => typeof v !== 'number')) { bad++; continue; }
  const cl = c.map(v => Math.max(0, Math.min(1000, v)));
  if (cl[2] <= cl[0] || cl[3] <= cl[1]) { bad++; continue; }
  valid.push(Object.assign({}, b, { box_2d: cl }));
}
// 2) IoU-дедуп > 0.7
const iou = (a, b) => {
  const ix = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const iy = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
  const inter = ix * iy;
  const union = (a[3] - a[1]) * (a[2] - a[0]) + (b[3] - b[1]) * (b[2] - b[0]) - inter;
  return union > 0 ? inter / union : 0;
};
valid.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
const keptAll = [];
let dups = 0;
for (const b of valid) {
  if (keptAll.some(k => iou(k.box_2d, b.box_2d) > 0.7)) { dups++; continue; }
  keptAll.push(b);
}
// 2b) фильтр щепок
const wOf = b => b.box_2d[3] - b.box_2d[1];
const shelfOf = b => Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
const widthsByShelf = new Map();
for (const b of keptAll) {
  const s = shelfOf(b);
  if (!widthsByShelf.has(s)) widthsByShelf.set(s, []);
  widthsByShelf.get(s).push(wOf(b));
}
const medW = new Map();
for (const [s, ws] of widthsByShelf) medW.set(s, [...ws].sort((a, b) => a - b)[Math.floor(ws.length / 2)]);
const slivers = [];
const kept = keptAll.filter(b => {
  const med = medW.get(shelfOf(b)) || 0;
  const atEdge = b.box_2d[1] <= 5 || b.box_2d[3] >= 995;
  if (!atEdge && med > 0 && wOf(b) < 0.7 * med) { slivers.push(b); return false; }
  return true;
});
const foreign = kept.filter(b => b.label === 'ЧУЖОЙ');
const ours = kept.filter(b => BRANDS.includes(b.label));

// ── позиционное сравнение по полкам
const gtUnits = [];
for (const sh of gt.shelves) for (const g of sh.groups)
  for (let i = 0; i < g.n; i++) gtUnits.push({ shelf: sh.shelf_index, brand: g.brand, subtype: g.subtype, format: g.format, verify: !!g.verify });

const byShelf = new Map();
for (const b of ours) {
  const s = shelfOf(b);
  if (!byShelf.has(s)) byShelf.set(s, []);
  byShelf.get(s).push(b);
}
for (const arr of byShelf.values()) arr.sort((p, q) => (p.box_2d[1] + p.box_2d[3]) - (q.box_2d[1] + q.box_2d[3]));

let stat = { count_gt: gtUnits.length, count_pred: ours.length, brand_ok: 0, subtype_ok: 0, subtype_null: 0, subtype_wrong: [], format_ok: 0, format_null: 0, format_scored: 0, format_wrong: [], positions_compared: 0 };
const shelfReport = [];
for (const sh of gt.shelves) {
  const gtRow = gtUnits.filter(u => u.shelf === sh.shelf_index);
  const predRow = byShelf.get(sh.shelf_index) || [];
  const n = Math.min(gtRow.length, predRow.length);
  shelfReport.push({ shelf: sh.shelf_index, gt: gtRow.length, pred: predRow.length });
  for (let i = 0; i < n; i++) {
    const g = gtRow[i], p = predRow[i];
    stat.positions_compared++;
    if (p.label === g.brand) stat.brand_ok++;
    if (p.subtype === g.subtype) stat.subtype_ok++;
    else if (p.subtype == null) stat.subtype_null++;
    else stat.subtype_wrong.push({ shelf: sh.shelf_index, pos: i + 1, gt: g.subtype, pred: p.subtype });
    if (g.format !== null) {
      stat.format_scored++;
      if (p.format === g.format) stat.format_ok++;
      else if (p.format == null) stat.format_null++;
      else stat.format_wrong.push({ shelf: sh.shelf_index, pos: i + 1, gt: g.format, pred: p.format });
    }
  }
}

console.log('=== СЧЁТ ===');
console.log(`боксов сырых: ${boxesIn.length}, bad: ${bad}, дубли: ${dups}, щепки: ${slivers.length}, ЧУЖОЙ: ${foreign.length}`);
console.log(`наших единиц: ${ours.length} / gt ${gtUnits.length}`);
for (const r of shelfReport) console.log(`  полка ${r.shelf}: pred ${r.pred} / gt ${r.gt} ${r.pred === r.gt ? '✓' : '✗'}`);
console.log('=== ПОЗИЦИОННО (слева направо), сравнено:', stat.positions_compared, '===');
console.log(`бренд: ${stat.brand_ok}/${stat.positions_compared}`);
console.log(`подвиды: ${stat.subtype_ok}/${stat.positions_compared} (null: ${stat.subtype_null}, ошибок: ${stat.subtype_wrong.length})`);
for (const w of stat.subtype_wrong) console.log(`  ✗ полка ${w.shelf} поз.${w.pos}: gt «${w.gt}» → «${w.pred}»`);
console.log(`форматы: ${stat.format_ok}/${stat.format_scored} (null: ${stat.format_null}, ошибок: ${stat.format_wrong.length}; Компотай полок 3–4 вне метрики)`);
const fmtAgg = {};
for (const w of stat.format_wrong) { const k = `${w.gt} → ${w.pred}`; fmtAgg[k] = (fmtAgg[k] || 0) + 1; }
for (const [k, v] of Object.entries(fmtAgg)) console.log(`  ✗ ${k}: ${v} шт.`);
if (data.notes) console.log('notes:', String(data.notes).slice(0, 300));
fs.writeFileSync(dataFile.replace('_data.json', '_score.json'), JSON.stringify({ shelfReport, stat, slivers, foreign_count: foreign.length }, null, 1));
