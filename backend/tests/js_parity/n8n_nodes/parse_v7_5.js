// Verbatim body of n8n Code node «Парсинг обработки Google Vision» from WF-2 v4.3 noreven export (01.09.2026).
// Used ONLY by tests/test_js_parity.py to check the Python port. Do not edit.
// v7.5-format-geo = v7.1-slivers + блок 3b (гео-арбитраж литража крупных ПЭТ).
// v7.1-slivers: парсинг ответа-детекции + ДЕТЕРМИНИРОВАННЫЙ счёт по боксам + ФОРМАТ ТАРЫ (№25)
// + фильтр «щепок» (серия H, 04.08: на документе Flash выдал фантомные боксы шириной 10 и 22
// при медиане полки 31–36 → счёт 67 вместо 65, план Pro-прохода поехал).
// Правило: ИНТЕРЬЕРНЫЙ бокс уже 0.7 медианной ширины своей полки → в диагностику, не в отчёт.
// Боксы у краёв кадра (x_min ≤ 5 или x_max ≥ 995) НЕ отсеиваются — частично видимые единицы
// включаем по промпту (правка п.6 от 27.07).
// Также в _detect добавлен finish_reason — контроль обрезания вывода (MAX_TOKENS/SAFETY).
const raw = $input.first().json;
const cand = raw.candidates?.[0];
const parts = cand?.content?.parts || [];
const textPart = [...parts].reverse().find(p => typeof p.text === 'string');
if (!textPart) {
  throw new Error('Нет текстового ответа Gemini: ' + JSON.stringify(raw).slice(0, 800));
}
const data = JSON.parse(textPart.text);

const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
const boxesIn = Array.isArray(data.boxes) ? data.boxes : [];

// 1) валидация координат
const valid = [];
let bad = 0;
for (const b of boxesIn) {
  const c = b && b.box_2d;
  if (!Array.isArray(c) || c.length !== 4 || c.some(v => typeof v !== 'number')) { bad++; continue; }
  const clamped = c.map(v => Math.max(0, Math.min(1000, v)));
  const y0 = clamped[0], x0 = clamped[1], y1 = clamped[2], x1 = clamped[3];
  if (y1 <= y0 || x1 <= x0) { bad++; continue; }
  valid.push(Object.assign({}, b, { box_2d: [y0, x0, y1, x1] }));
}

// 2) дедуп: IoU > 0.7 → остаётся бокс с большей confidence
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

// 2b) фильтр «щепок»: аномально узкие интерьерные боксы — артефакты детекции, не товар
const wOf = b => b.box_2d[3] - b.box_2d[1];
const shelfOf = b => Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
const widthsByShelf = new Map();
for (const b of keptAll) {
  const s = shelfOf(b);
  if (!widthsByShelf.has(s)) widthsByShelf.set(s, []);
  widthsByShelf.get(s).push(wOf(b));
}
const medW = new Map();
for (const [s, ws] of widthsByShelf) {
  const sorted = [...ws].sort((a, b) => a - b);
  medW.set(s, sorted[Math.floor(sorted.length / 2)]);
}
const sliversDropped = [];
const kept = keptAll.filter(b => {
  const med = medW.get(shelfOf(b)) || 0;
  const atEdge = b.box_2d[1] <= 5 || b.box_2d[3] >= 995;
  if (!atEdge && med > 0 && wOf(b) < 0.7 * med) { sliversDropped.push(b); return false; }
  return true;
});

// 3) ЧУЖОЙ — в диагностику, не в отчёт
const foreign = kept.filter(b => b.label === 'ЧУЖОЙ');
const ours = kept.filter(b => BRANDS.includes(b.label));

// ── 3b) ФОРМАТ-ГЕО (v7.5, №25-геометрия): арбитраж литража КРУПНЫХ ПЭТ по ширине боксов.
// Калибровка 10.08.2026 на живых боксах Flash (IMG_0643, gt-66): w_rel = ширина бокса ÷ span
// ряда полки; отношение к якорю «банка 0,45 л»: 1 л ≈ 1.18 · 1,5 л ≈ 1.33 · 2 л ≈ 1.54
// (физика диаметров 1.24/1.39/1.58; систематика боксов ≈ −4% сокращается отношением).
// Применяется ТОЛЬКО: плотный полный ряд (гейты density/span), группы ≥3, бренды с крупными ПЭТ,
// есть якорь-банка. 0,5↔1 л НЕ трогаем (шириной не разделяются — калибровка 10.08). Пороги —
// отношениями к якорю, не абсолютами. Диагностика: _detect.format_geo. Ручка: GEO.enabled.
const GEO = { enabled: true, r_1_15: 1.25, r_15_2: 1.43, r_floor: 1.10,
  minGroup: 3, minShelf: 4, densLo: 0.9, densHi: 1.3, spanFrac: 0.8, minAnchor: 3 };
const GEO_ENUM = { 'Буратино': ['ПЭТ 1 л', 'ПЭТ 1,5 л', 'ПЭТ 2 л'], 'Компотай': ['ПЭТ 1 л', 'ПЭТ 1,5 л'] };
const geoDiag = { enabled: GEO.enabled, anchor: null, groups: [] };
if (GEO.enabled) (() => {
  const wOf2 = b => b.box_2d[3] - b.box_2d[1];
  const medOf = xs => { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
  const byShelfAll = new Map();
  for (const b of ours) { const s = shelfOf(b); if (!byShelfAll.has(s)) byShelfAll.set(s, []); byShelfAll.get(s).push(b); }
  const meta = new Map();
  let maxSpan = 0;
  for (const [s, arr] of byShelfAll) {
    const span = Math.max(...arr.map(b => b.box_2d[3])) - Math.min(...arr.map(b => b.box_2d[1]));
    const dens = span > 0 ? arr.reduce((a, b) => a + wOf2(b), 0) / span : 0;
    meta.set(s, { span, dens, n: arr.length });
    if (span > maxSpan) maxSpan = span;
  }
  const shelfOk = s => { const m = meta.get(s);
    return !!m && m.n >= GEO.minShelf && m.dens >= GEO.densLo && m.dens <= GEO.densHi && m.span >= GEO.spanFrac * maxSpan; };
  // якорь кадра: медианная относительная ширина банок 0,45 на валидных полках
  const cans = ours.filter(b => b.format === 'банка 0,45 л' && shelfOk(shelfOf(b)));
  if (cans.length < GEO.minAnchor) { geoDiag.anchor = { ok: false, cans: cans.length }; return; }
  const anchor = medOf(cans.map(b => wOf2(b) / meta.get(shelfOf(b)).span));
  geoDiag.anchor = { ok: true, w_rel: +anchor.toFixed(4), cans: cans.length };
  // целевые группы: (полка, бренд, формат) — только крупные ПЭТ и null-ПЭТ брендов из GEO_ENUM
  const tg = new Map();
  for (const b of ours) {
    const allowed = GEO_ENUM[b.label];
    if (!allowed) continue;
    const f = b.format || null;
    if (f !== null && allowed.indexOf(f) === -1) continue;   // банка / 0,5 / 2,4 — не трогаем
    if (!shelfOk(shelfOf(b))) continue;
    const k = shelfOf(b) + '|' + b.label + '|' + (f || 'null');
    if (!tg.has(k)) tg.set(k, []);
    tg.get(k).push(b);
  }
  for (const [k, arr] of tg) {
    const brand = k.split('|')[1];
    if (arr.length < GEO.minGroup) { geoDiag.groups.push({ key: k, n: arr.length, kept: 'мало боксов' }); continue; }
    const r = medOf(arr.map(b => wOf2(b) / meta.get(shelfOf(b)).span)) / anchor;
    if (r < GEO.r_floor) { geoDiag.groups.push({ key: k, n: arr.length, r: +r.toFixed(3), kept: 'зона 0,5/1 л' }); continue; }
    let to = r < GEO.r_1_15 ? 'ПЭТ 1 л' : r < GEO.r_15_2 ? 'ПЭТ 1,5 л' : 'ПЭТ 2 л';
    const allowed = GEO_ENUM[brand];
    if (allowed.indexOf(to) === -1) to = allowed[allowed.length - 1];  // enum-cap бренда (у Компотая нет 2 л)
    const changed = arr.filter(b => (b.format || null) !== to).length;
    arr.forEach(b => { b.format = to; });
    geoDiag.groups.push({ key: k, n: arr.length, r: +r.toFixed(3), to, changed });
  }
})();

// 4) группировка (полка, бренд, подвид, ФОРМАТ) → items; счёт = ЧИСЛО БОКСОВ
const groups = new Map();
for (const b of ours) {
  const shelf = Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
  const fmt = b.format || null;
  const key = shelf + '|' + b.label + '|' + (b.subtype || '') + '|' + (fmt || '');
  if (!groups.has(key)) groups.set(key, { shelf, brand: b.label, subtype: b.subtype || null, format: fmt, boxes: [] });
  groups.get(key).boxes.push(b);
}

const loc = x => x < 333 ? 'слева' : x < 667 ? 'центр' : 'справа';
const items = [...groups.values()].map(g => {
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

return [{ json: {
  shelves_with_target_product: new Set(items.map(i => i.shelf_index)).size,
  items,
  store_code_on_card: data.store_code_on_card ?? null,
  overall_confidence: typeof data.overall_confidence === 'number' ? data.overall_confidence : null,
  notes: data.notes || '',
  _detect: {                       // диагностика в executions
    boxes_total: boxesIn.length,
    boxes_bad: bad,
    dedup_dropped: dups,
    slivers_dropped: sliversDropped.length,          // серия H: фантомы-щепки
    slivers_raw: sliversDropped,                      // сами щепки — для box_viewer
    foreign_units: foreign.length,
    format_null: ours.filter(b => !b.format).length,
    format_geo: geoDiag,                              // v7.5: арбитраж литража по ширине
    finish_reason: (cand && cand.finishReason) || null, // контроль обрезания вывода
    boxes_raw: kept,
  },
  _usage: {
    prompt_tokens: raw.usageMetadata?.promptTokenCount ?? null,
    cached_tokens: raw.usageMetadata?.cachedContentTokenCount ?? null,
    output_tokens: raw.usageMetadata?.candidatesTokenCount ?? null,
  },
} }];
