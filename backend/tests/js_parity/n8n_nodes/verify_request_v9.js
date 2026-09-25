// Verbatim body of n8n Code node «Сборка запроса Pro» from WF-2 v4.3 noreven export (01.09.2026).
// Used ONLY by tests/test_js_parity.py to check the Python port. Do not edit.
// v9 ПРОХОД 2 «ГРУППЫ»: модель называет подвид ЦЕЛЫХ ГРУПП по границам Flash —
// перечисление юнитов убрано совсем. Мотив: guard v4.2 и так принимает только
// переименования целых групп; просить последовательность юнитов = лишние степени
// свободы, которые дрейфуют (серия H: 3+3+3+3+3+5 vs 3+4+4+3+3+3) и идут в мусор.
// Границы групп зафиксированы Flash'ем by construction → дрейф невозможен.
// Имена подвидов Flash модели НЕ показываем (якорь «ревень»); бренд группы показываем.
// Правила SUBTYPE (цвет сначала, запрет типа чая) — байт-в-байт из v8.
// Замена тела ноды «Сборка запроса Pro». Модель-namer выбирается URL'ом HTTP-ноды.
const parsed = $input.first().json;
const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
const UNKNOWN = 'НЕ ОПРЕДЕЛЁН';

const boxes = ((parsed._detect && parsed._detect.boxes_raw) || []).filter(b => b && BRANDS.includes(b.label));
if (!boxes.length) return [{ json: { pass2_skip: true, reason: 'нет боксов наших брендов' } }];

// ── группировка: полка → слева направо → последовательные с одинаковым (label, subtype)
// ВАЖНО: тот же алгоритм скопирован в «Слиянии v9» — менять только синхронно.
const shelfOf = b => Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
const byShelf = new Map();
for (const b of boxes) {
  const s = shelfOf(b);
  if (!byShelf.has(s)) byShelf.set(s, []);
  byShelf.get(s).push(b);
}
const shelvesPlan = [];
for (const [shelf_index, arr] of [...byShelf.entries()].sort((a, b) => a[0] - b[0])) {
  arr.sort((p, q) => p.box_2d[1] - q.box_2d[1]);
  const groups = [];
  let pos = 0;
  while (pos < arr.length) {
    const brand = arr[pos].label, sub = arr[pos].subtype || null;
    let end = pos;
    while (end < arr.length && arr[end].label === brand && (arr[end].subtype || null) === sub) end++;
    groups.push({ group_index: groups.length + 1, brand, size: end - pos });
    pos = end;
  }
  shelvesPlan.push({ shelf_index, count: arr.length, groups });
}
const planText = shelvesPlan.map(s =>
  'полка ' + s.shelf_index + ' (' + s.count + ' шт. слева направо): '
  + s.groups.map(g => 'группа ' + g.group_index + ' — ' + g.size + ' шт., бренд ' + g.brand).join('; ')
).join('\n');

// ── справочник эталонов: тот же порядок, что в проходе 1 (implicit-кеш любит одинаковый префикс)
let rowsAll = $('Каталог брендов: Config').all().map(i => i.json).filter(r => r.file_url && r.canon_name);
if (rowsAll.length < 20) throw new Error('WF-2 v9: в Catalog только ' + rowsAll.length + ' эталонов — прогони WF-3');

// ── ВРЕМЕННОЕ ИСКЛЮЧЕНИЕ ПОДВИДОВ ИЗ КАТАЛОГА (31.08.2026) ──────────────────
// Ревень снят с выборки: полевых фото вкуса нет, SKU предположительно снят с производства.
// Пока ключ в списке — подвида нет НИ в справочнике эталонов, НИ в enum схемы,
// то есть модель о нём не знает вовсе (лечит имя-паразит: ревень без хозяина на полке
// липнул к самой розовой группе — персик/клубника).
// ВЕРНУТЬ РЕВЕНЬ = очистить массив:  const EXCLUDE_KEYS = [];   ← и больше ничего.
// Сравнивается базовый key: точное совпадение ИЛИ key + '__<вариант>' — ловит __rot, __kz, __ru, __pet1000, __can900,
// и НЕ заденет посторонний подвид с похожим началом имени.
const EXCLUDE_KEYS = ['aitea_reven'];
const isExcluded = r => { const k = String(r.key || ''); return EXCLUDE_KEYS.some(p => k === p || k.startsWith(p + '__')); };
rowsAll = rowsAll.filter(r => !isExcluded(r));
rowsAll.sort((a, b) => String(a.brand).localeCompare(String(b.brand), 'ru')
  || String(a.canon_name).localeCompare(String(b.canon_name), 'ru')
  || String(a.key).localeCompare(String(b.key), 'ru'));
const SUBTYPES = [...new Set(rowsAll.map(r => String(r.canon_name)))].filter(c => c !== 'Tamga');

const variantOf = r => {
  if (r.variant) return String(r.variant);
  const k = String(r.key), i = k.indexOf('__');
  return i === -1 ? null : k.slice(i + 2);
};
const VARIANT_NOTE = v => {
  if (!v) return null;
  const parts = [];
  if (/(^|_)kz($|_)/.test(v)) parts.push('этикетка на казахском');
  if (/(^|_)ru($|_)/.test(v)) parts.push('этикетка на русском');
  if (/rot/.test(v)) parts.push('повёрнутый ракурс');
  if (v === 'field') parts.push('полевое фото с полки');
  if (/^can900/.test(v)) parts.push('банка 0,9 л');
  else if (/^can/.test(v)) parts.push('банка крупным планом');
  if (/^sleever/.test(v)) parts.push('ПЭТ-бутылка 1 л с цветным рукавом');
  if (/^pet1000/.test(v)) parts.push('ПЭТ-бутылка 1 л');
  else if (/^pet(\d+)/.test(v)) {
    const m = v.match(/^pet(\d+)/)[1];
    const vol = { '025': '0,25', '05': '0,5', '1': '1', '15': '1,5', '2': '2', '24': '2,4' }[m] || m;
    parts.push('ПЭТ-бутылка ' + vol + ' л');
  }
  return parts.length ? parts.join(', ') : 'дополнительный ракурс (' + v + ')';
};

// ── mime целевого фото: как в проходе 1
const MIME_OK = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif']);
let photoMime = null;
try { photoMime = $('Загрузка фото').first().binary.data.mimeType; } catch (e) {}
if (!MIME_OK.has(String(photoMime))) { try { photoMime = $('Закрепляю тип фотографии').first().json.file_mime; } catch (e) {} }
if (!MIME_OK.has(String(photoMime))) photoMime = 'image/jpeg';

const SYSTEM_PROMPT = 'Ты — система визуального аудита выкладки товара. Единицы товара на фото УЖЕ обведены, посчитаны и сгруппированы другой системой: подряд стоящие одинаковые единицы объединены в ГРУППЫ. Координаты и пересчёт не нужны.\n\n'
  + 'ЗАДАЧА: для КАЖДОЙ группы из плана назвать ОДИН подвид — тот, которым являются все единицы этой группы. Группы в плане идут слева направо по каждой полке; их границы и размеры уже проверены — не объединяй и не дели группы.\n\n'
  + 'ВХОД: сначала СПРАВОЧНИК — эталонные изображения подвидов, перед каждым текстовая метка с канон-именем и брендом. Затем целевое фото и ПЛАН групп по полкам.\n\n'
  + "SUBTYPE группы — определяй ПО ШАГАМ:\n1. Найди группу на фото: полка из плана, отсчёт групп слева направо по указанным размерам.\n2. ЦВЕТ СНАЧАЛА: определи доминирующий цвет корпуса/этикетки единиц группы и отбери эталоны её бренда с таким цветом — это шорт-лист кандидатов.\n3. Разведи кандидатов шорт-листа по остальным признакам: цвет крышки, изображённые плоды, надписи на этикетке — сверяясь с эталонами.\n4. Если после шагов 2–3 остаётся больше одного кандидата — ставь «НЕ ОПРЕДЕЛЁН».\n\n⚠️ ЦВЕТ КОРПУСА — ЖЁСТКОЕ ОГРАНИЧЕНИЕ. Подвид, у которого корпус зелёный (гуава, помело, лимон-лайм-жасмин), не может оказаться на малиновой, красной, розовой или оранжевой единице, и наоборот. Никакой другой признак — ни цвет букв, ни надпись, ни крышка — не может переопределить цвет корпуса.\n\n⚠️ ТИП ЧАЯ НЕ ЯВЛЯЕТСЯ ПРИЗНАКОМ ПОДВИДА. Слова БЕЛЫЙ ЧАЙ / ЗЕЛЕНЫЙ ЧАЙ / ЧЕРНЫЙ ЧАЙ и АҚ ШАЙЫ / КӨК ШАЙЫ / ҚАРА ШАЙЫ встречаются у нескольких разных подвидов сразу. Никогда не выбирай подвид по типу чая. Название вкуса на этикетке («МАНГО + МАРАКУЙЯ», «ПЕРСИК + ЖАСМИН», «КЛУБНИЧНЫЙ + КИВИ», «ПОМЕЛО + АПЕЛЬСИН») — наоборот, самый прямой признак: прочитал его — используй.\n\n- Пиши ТОЧНОЕ канон-имя из метки эталона, не меняя ни символа. Бренд группы указан в плане — подвид обязан быть подвидом ЭТОГО бренда.\n- Каждую группу решай индивидуально, не копируй подвид соседней группы.\n- Не уверен — «НЕ ОПРЕДЕЛЁН»: пустое значение лучше уверенной ошибки.\n- Tamga: подвидов нет — для групп бренда Tamga всегда «НЕ ОПРЕДЕЛЁН».\n\nВЫВОД: строго валидный JSON по схеме. Без текста вне JSON.";

const parts = [];
const hasVariants = rowsAll.some(r => variantOf(r));
parts.push({ text: 'СПРАВОЧНИК ПОДВИДОВ КОМПАНИИ. Далее эталонные изображения; перед каждым — его канон-имя и бренд'
  + (hasVariants ? '; у подвида может быть несколько эталонов (другой язык этикетки, другой ракурс или другая тара) — это один и тот же подвид' : '') + ':' });
const seen = new Set();
for (const r of rowsAll) {
  const note = VARIANT_NOTE(variantOf(r));
  if (!seen.has(r.canon_name)) {
    seen.add(r.canon_name);
    parts.push({ text: 'Эталон: «' + r.canon_name + '» — бренд ' + r.brand + '.' + (note ? ' (' + note + ')' : '') });
  } else {
    parts.push({ text: 'Тот же подвид «' + r.canon_name + '», ' + (note || 'дополнительный эталон') + '.' });
  }
  parts.push({ file_data: { mime_type: r.mime_type || 'image/png', file_uri: r.file_url } });
}
const photoPart = { inline_data: { mime_type: photoMime, data: $('Перевод фото в строку').first().json.data } };
photoPart.media_resolution = { level: 'MEDIA_RESOLUTION_ULTRA_HIGH' };
parts.push({ text: 'ЭТО целевое фото:' });
parts.push(photoPart);
parts.push({ text: 'ПЛАН ГРУПП (границы и размеры уже проверены, счёт менять нельзя):\n' + planText
  + '\n\nВерни подвид для КАЖДОЙ группы каждой полки.' });

const RESPONSE_SCHEMA = {
  type: 'object',
  propertyOrdering: ['shelves'],
  properties: {
    shelves: {
      type: 'array',
      items: {
        type: 'object',
        propertyOrdering: ['shelf_index', 'groups'],
        properties: {
          shelf_index: { type: 'integer' },
          groups: {
            type: 'array',
            items: {
              type: 'object',
              propertyOrdering: ['group_index', 'subtype'],
              properties: {
                group_index: { type: 'integer' },
                subtype: { type: 'string', enum: [...SUBTYPES, UNKNOWN] },
              },
              required: ['group_index', 'subtype'],
            },
          },
        },
        required: ['shelf_index', 'groups'],
      },
    },
  },
  required: ['shelves'],
};

return [{ json: {
  gemini_body: {
    systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: [{ role: 'user', parts }],
    generationConfig: { temperature: 0, response_mime_type: 'application/json', response_schema: RESPONSE_SCHEMA },
  },
  v9_plan: shelvesPlan,
  refs_count: rowsAll.length,
  pass2_version: 'v9-groups-noreven',
} }];
