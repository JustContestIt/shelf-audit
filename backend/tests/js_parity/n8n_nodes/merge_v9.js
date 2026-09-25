// Verbatim body of n8n Code node «Слияние подвидов» from WF-2 v4.3 noreven export (01.09.2026).
// Used ONLY by tests/test_js_parity.py to check the Python port. Do not edit.
// v9 СЛИЯНИЕ «ГРУППЫ»: имена групп из прохода 2 накладываются на боксы Flash по
// (полка, номер группы). Границы групп пересчитываются тем же алгоритмом, что в
// «Сборке v9» (копия — менять синхронно!), поэтому расхождение структуры невозможно.
// Guard бренда сохранён (v4.2). Отступление от v4.2: «НЕ ОПРЕДЕЛЁН» НЕ затирает
// подвид Flash в null, а оставляет его и помечает группу в needs_review — у Flash
// есть уверенное имя, неуверенность проверяющего не повод его терять.
// Замена тела ноды «Слияние подвидов» для серии v9.
const parsed = $('Парсинг обработки Google Vision').first().json;
const raw = $input.first().json;
const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
const UNKNOWN = 'НЕ ОПРЕДЕЛЁН';

let pass2 = null;
try {
  const parts = (raw.candidates && raw.candidates[0] && raw.candidates[0].content && raw.candidates[0].content.parts) || [];
  const t = [...parts].reverse().find(p => typeof p.text === 'string');
  if (t) pass2 = JSON.parse(t.text);
} catch (e) { pass2 = null; }

const kept = (parsed._detect && parsed._detect.boxes_raw) || [];
const ours = kept.filter(b => b && BRANDS.includes(b.label));

// ── группировка: КОПИЯ алгоритма «Сборки v9»
const shelfOf = b => Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
const byShelf = new Map();
for (const b of ours) {
  const s = shelfOf(b);
  if (!byShelf.has(s)) byShelf.set(s, []);
  byShelf.get(s).push(b);
}
const groupsByShelf = new Map();
for (const [shelf_index, arr] of byShelf) {
  arr.sort((p, q) => p.box_2d[1] - q.box_2d[1]);
  const groups = [];
  let pos = 0;
  while (pos < arr.length) {
    const brand = arr[pos].label, sub = arr[pos].subtype || null;
    let end = pos;
    while (end < arr.length && arr[end].label === brand && (arr[end].subtype || null) === sub) end++;
    groups.push({ group_index: groups.length + 1, brand, boxes: arr.slice(pos, end) });
    pos = end;
  }
  groupsByShelf.set(shelf_index, groups);
}

// ── наложение имён
const stats = [];
let changed = 0, needsReview = 0;
if (pass2 && Array.isArray(pass2.shelves)) {
  for (const sh of pass2.shelves) {
    const groups = groupsByShelf.get(sh.shelf_index);
    if (!groups) { stats.push({ shelf: sh.shelf_index, applied: false, reason: 'у Flash нет такой полки' }); continue; }
    const details = [];
    for (const g of (sh.groups || [])) {
      const grp = groups.find(x => x.group_index === g.group_index);
      if (!grp) { details.push({ gi: g.group_index, applied: false, reason: 'нет такой группы у Flash' }); continue; }
      const nv = (g.subtype && g.subtype !== UNKNOWN) ? g.subtype : null;
      if (nv === null) {                             // НЕ ОПРЕДЕЛЁН → оставить Flash, пометить
        needsReview++;
        details.push({ gi: g.group_index, applied: false, reason: 'pass2 не уверен — оставлен Flash', needs_review: true });
        continue;
      }
      if (nv.indexOf(grp.brand) !== 0) {             // guard бренда (v4.2)
        details.push({ gi: g.group_index, applied: false, reason: 'подпись чужого бренда: ' + nv });
        continue;
      }
      let c = 0;
      grp.boxes.forEach(b => { if ((b.subtype || null) !== nv) c++; b.subtype = nv; });
      changed += c;
      details.push({ gi: g.group_index, applied: true, changed: c, name: nv });
    }
    stats.push({ shelf: sh.shelf_index, applied: details.some(d => d.applied), groups: details });
  }
} else {
  stats.push({ shelf: null, applied: false, reason: 'проход 2 не ответил или ответ не разобрался' });
}

// ── пересборка items — та же группировка, что в «Парсинге» (полка, бренд, подвид, формат)
const groups2 = new Map();
for (const b of ours) {
  const shelf = shelfOf(b);
  const fmt = b.format || null;
  const key = shelf + '|' + b.label + '|' + (b.subtype || '') + '|' + (fmt || '');
  if (!groups2.has(key)) groups2.set(key, { shelf, brand: b.label, subtype: b.subtype || null, format: fmt, boxes: [] });
  groups2.get(key).boxes.push(b);
}
const loc = x => x < 333 ? 'слева' : x < 667 ? 'центр' : 'справа';
const items = [...groups2.values()].map(g => {
  const centers = g.boxes.map(b => (b.box_2d[1] + b.box_2d[3]) / 2);
  const meanX = centers.reduce((s, v) => s + v, 0) / centers.length;
  return {
    product_name: g.brand,
    product_subtype: g.subtype,
    package_format: g.format,
    shelf_index: g.shelf,
    shelf_location: loc(meanX),
    front_facing_count: g.boxes.length,
    confidence: Math.min.apply(null, g.boxes.map(b => typeof b.confidence === 'number' ? b.confidence : 1)),
    _x: meanX,
  };
}).sort((a, b) => a.shelf_index - b.shelf_index || a._x - b._x);
items.forEach(i => { delete i._x; });

return [{ json: Object.assign({}, parsed, {
  items,
  shelves_with_target_product: new Set(items.map(i => i.shelf_index)).size,
  _pass2: {
    version: 'v9-groups',
    shelves_applied: stats.filter(s => s.applied).length,
    shelves_total: groupsByShelf.size,
    subtypes_changed: changed,
    needs_review: needsReview,
    detail: stats,
    usage: {
      prompt_tokens: (raw.usageMetadata && raw.usageMetadata.promptTokenCount) || null,
      cached_tokens: (raw.usageMetadata && raw.usageMetadata.cachedContentTokenCount) || null,
      output_tokens: (raw.usageMetadata && raw.usageMetadata.candidatesTokenCount) || null,
    },
  },
}) }];
