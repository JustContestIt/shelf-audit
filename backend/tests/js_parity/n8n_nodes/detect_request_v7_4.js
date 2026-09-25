// Verbatim body of n8n Code node «Сборка запроса Gemini» from WF-2 v4.3 noreven export (01.09.2026).
// Used ONLY by tests/test_js_parity.py to check the Python port. Do not edit.
// v7.1 БЛИЗНЕЦЫ: v7 (формат/литраж) + контраст-правила трёх пар-близнецов AI TEA (серия E).
// Единственный источник промпта и тела запроса для ОБЕИХ Gemini Vision-нод.
// Изменение против v7 ровно одно: блок «ПАРЫ-БЛИЗНЕЦЫ» в конце SUBTYPE (+ маркер версии).
// Признаки пар выведены из мокапов эталонов (просмотрены бок-о-бок 2026-07-29), не из памяти.

// ── РУЧКИ ЗАМЕРА ─────────────────────────────────────────────
// ULTRA_HIGH = базовая конфигурация с 2026-07-27 (решение Никиты: оставить включённым).
// ⚠️ Если в ТВОЕЙ живой ноде значение другое — сохрани его, не моё.
const TARGET_MEDIA_RESOLUTION = 'MEDIA_RESOLUTION_ULTRA_HIGH';
const MEDIA_RESOLUTION = null;

// ── ФОРМАТЫ ТАРЫ (№25) ───────────────────────────────────────
// Фиксированный список: форматы, в отличие от подвидов, меняются редко — новый формат
// добавлять СЮДА и в блок «Допустимые форматы» промпта. Состав собран по мокапам заказчика
// (README_ALL); после SKU-справочника заказчика сверить и поправить.
const FORMATS = ['банка 0,45 л', 'банка 0,9 л', 'ПЭТ 0,25 л', 'ПЭТ 0,5 л', 'ПЭТ 1 л', 'ПЭТ 1,5 л', 'ПЭТ 2 л', 'ПЭТ 2,4 л'];

const rowsAll = $('Каталог брендов: Config').all().map(i => i.json).filter(r => r.file_url && r.canon_name);
if (rowsAll.length < 20) throw new Error('WF-2: в Catalog только ' + rowsAll.length + ' эталонов с file_url — прогони WF-3');

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

// Ветка скана брендов удалена 03.08 (пользы не давала, C2 закрыта) — эталоны шлём все.
const scanBrands = null;
let rows = rowsAll.filter(r => !isExcluded(r));

// стабильный порядок: бренд → подвид → key (база раньше вариантов; implicit-кеш любит байт-в-байт одинаковый префикс)
rows.sort((a, b) => String(a.brand).localeCompare(String(b.brand), 'ru')
  || String(a.canon_name).localeCompare(String(b.canon_name), 'ru')
  || String(a.key).localeCompare(String(b.key), 'ru'));

const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
// enum подвидов: УНИКАЛЬНЫЕ канон-имена (вариантные строки дублируют имя, в схему дубли нельзя)
const SUBTYPES = [...new Set(rows.map(r => String(r.canon_name)))].filter(c => c !== 'Tamga');

const SYSTEM_PROMPT = `Ты — система визуального аудита выкладки товара. Твоя задача — ДЕТЕКЦИЯ, а не подсчёт: обведи рамкой каждую единицу товара наших брендов в переднем ряду. Итоговые количества посчитает программа по твоим рамкам, поэтому важна каждая отдельная рамка, а не «примерное число».

ВХОД: сначала СПРАВОЧНИК — эталонные изображения подвидов, перед каждым текстовая метка с канон-именем и брендом. Затем целевое фото полки или стойки.

Detect the 2D bounding boxes of every front-row product unit of the company brands.

БРЕНДЫ (label): Буратино, AI TEA, Chino, Компотай, Tamga.

ПРАВИЛА ДЕТЕКЦИИ:
1. Один физический предмет (банка/бутылка) = ровно один бокс. Одинаковые банки, стоящие вплотную, — отдельные боксы каждой, не один общий.
2. Боксируй только ПЕРЕДНИЙ ряд, обращённый к камере. Товар за передним рядом, скрытый запас и мультипаки фоном не боксируй.
3. Частично видимые единицы с краёв кадра боксируй.
4. Работай системно: полка за полкой сверху вниз, в пределах полки слева направо. Полки нумеруй сверху вниз: верхняя = 1; каждому боксу проставь shelf_index его полки.
5. box_2d = [y_min, x_min, y_max, x_max], координаты нормированы 0–1000.
6. Не боксируй только ДРУГИЕ стеллажи — отделённые от основного рамой, стенкой или проходом. Внутри основного стеллажа/витрины боксируй ВСЕ единицы на всех полках, включая стоящие у самого края кадра и частично обрезанные (п. 3).

LABEL И ЗАЩИТА ОТ ЧУЖОГО:
- label определяй по логотипу и упаковке, сверяясь с эталонами.
- Единица ПОХОЖА на наш бренд, но логотип/этикетка не совпадает с эталонами (марка-двойник) — ставь label: ЧУЖОЙ. Такие боксы не попадут в отчёт: это защита от зачисления чужого товара в наши.
- ЧУЖОЙ ставь только при явном отличии от эталонов. Если единица просто плохо видна, но похожа на наш бренд — наш label и subtype: null.
- Очевидно чужой товар (другая категория, другое оформление) не боксируй вовсе.

SUBTYPE — определяй для каждого бокса ПО ШАГАМ:
1. ЦВЕТ СНАЧАЛА: определи доминирующий цвет корпуса/этикетки этой единицы и отбери эталоны её бренда с таким цветом — это шорт-лист кандидатов.
2. Разведи кандидатов шорт-листа по остальным признакам: цвет крышки, изображённые плоды, надписи на этикетке — сверяясь с эталонами.
3. Если после шагов 1–2 остаётся больше одного кандидата — ставь null, бокс при этом остаётся.

⚠️ ЦВЕТ КОРПУСА — ЖЁСТКОЕ ОГРАНИЧЕНИЕ. Подвид, у которого корпус зелёный (гуава, помело, лимон-лайм-жасмин), не может оказаться на малиновой, красной, розовой или оранжевой единице, и наоборот. Никакой другой признак — ни цвет букв, ни надпись, ни крышка — не может переопределить цвет корпуса: эти признаки работают ТОЛЬКО внутри уже отобранного по корпусу шорт-листа.

⚠️ ТИП ЧАЯ НЕ ЯВЛЯЕТСЯ ПРИЗНАКОМ ПОДВИДА. Слова БЕЛЫЙ ЧАЙ / ЗЕЛЕНЫЙ ЧАЙ / ЧЕРНЫЙ ЧАЙ и АҚ ШАЙЫ / КӨК ШАЙЫ / ҚАРА ШАЙЫ встречаются у нескольких разных подвидов сразу. Никогда не выбирай подвид по типу чая. Название вкуса на этикетке («МАНГО + МАРАКУЙЯ», «ПЕРСИК + ЖАСМИН», «КЛУБНИЧНЫЙ + КИВИ», «ПОМЕЛО + АПЕЛЬСИН») — наоборот, самый прямой признак: прочитал его — используй.

- Пиши ТОЧНОЕ канон-имя из метки эталона, не меняя ни символа.
- Каждую единицу решай индивидуально, не копируй подвид от соседа — рядом могут стоять разные подвиды одного бренда.
- Не уверен — ставь null: пустое значение лучше уверенной ошибки.
- Tamga: подвидов нет — всегда null.

FORMAT — тара и объём каждого бокса, ПО ШАГАМ:
1. ТИП ТАРЫ по силуэту: металлическая банка (ровный цилиндр, плоский верх, без крышки-колпачка) или ПЭТ-бутылка (сужение к горлышку, пластиковая крышка).
2. ОБЪЁМ по пропорциям и соседям: банка 0,9 л заметно выше и вытянутее банки 0,45 л; объём ПЭТ оценивай по высоте бутылки относительно соседних единиц, чей формат уже ясен, и относительно высоты полки.
3. Ряд одинаковых единиц одного бренда и подвида — один формат: определи по самой различимой единице ряда и присвой остальным единицам ряда.
Допустимые форматы по брендам: AI TEA — банка 0,45 л, банка 0,9 л, ПЭТ 0,5 л, ПЭТ 1 л. Компотай — банка 0,45 л, ПЭТ 0,25 л, ПЭТ 0,5 л, ПЭТ 1 л, ПЭТ 1,5 л; бутылка Компотая в цветном рукаве-плёнке во весь корпус = ПЭТ 1 л. Буратино — банка 0,45 л, ПЭТ 0,5 л, ПЭТ 1 л, ПЭТ 1,5 л, ПЭТ 2 л, ПЭТ 2,4 л. Chino и Tamga — format всегда null.
- Формат определяй по единице НА ФОТО: эталон подвида может быть снят в другой таре — эталоны сверяй для label и subtype, а не для format.
- Не уверен в объёме — ставь format: null, бокс остаётся. Неуверенность в формате НЕ влияет на label и subtype.

ДОПОЛНИТЕЛЬНО:
- store_code_on_card: рукописный код с карточки в кадре (например «231»), иначе null.
- overall_confidence (0..1): качество кадра — резкость, блики, ракурс, перекрытия.
- notes: коротко, что мешало (блики, перекрытия), какие подвиды не различил, был ли рядом чужой товар-двойник.

ВЫВОД: строго валидный JSON по схеме. Без текста вне JSON.`;

const RESPONSE_SCHEMA = {
  type: 'object',
  propertyOrdering: ['boxes', 'store_code_on_card', 'overall_confidence', 'notes'],
  properties: {
    boxes: {
      type: 'array',
      items: {
        type: 'object',
        propertyOrdering: ['box_2d', 'label', 'subtype', 'format', 'shelf_index', 'confidence'],
        properties: {
          box_2d: { type: 'array', items: { type: 'integer' }, minItems: 4, maxItems: 4 },
          label: { type: 'string', enum: BRANDS.concat(['ЧУЖОЙ']) },
          subtype: { type: 'string', enum: SUBTYPES, nullable: true },
          format: { type: 'string', enum: FORMATS, nullable: true },
          shelf_index: { type: 'integer' },
          confidence: { type: 'number' }
        },
        required: ['box_2d', 'label', 'subtype', 'format', 'shelf_index', 'confidence']
      }
    },
    store_code_on_card: { type: 'string', nullable: true },
    overall_confidence: { type: 'number' },
    notes: { type: 'string' }
  },
  required: ['boxes', 'overall_confidence']
};

// ── варианты эталона: подпись (обобщённая версия из README_ALL, знает все токены форматов) ──
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
    const vol = {'025':'0,25','05':'0,5','1':'1','15':'1,5','2':'2','24':'2,4'}[m] || m;
    parts.push('ПЭТ-бутылка ' + vol + ' л');
  }
  return parts.length ? parts.join(', ') : 'дополнительный ракурс (' + v + ')';
};

const hasVariants = rows.some(r => variantOf(r));
const parts = [];
parts.push({ text: 'СПРАВОЧНИК ПОДВИДОВ КОМПАНИИ. Далее эталонные изображения; перед каждым — его канон-имя и бренд'
  + (hasVariants ? '; у подвида может быть несколько эталонов (другой язык этикетки, другой ракурс или другая тара) — это один и тот же подвид' : '') + ':' });
const seen = new Set();
for (const r of rows) {
  const note = VARIANT_NOTE(variantOf(r));
  if (!seen.has(r.canon_name)) {
    seen.add(r.canon_name);
    parts.push({ text: `Эталон: «${r.canon_name}» — бренд ${r.brand}.` + (note ? ` (${note})` : '') });
  } else {
    parts.push({ text: `Тот же подвид «${r.canon_name}», ${note || 'дополнительный эталон'}.` });
  }
  parts.push({ file_data: { mime_type: r.mime_type || 'image/png', file_uri: r.file_url } });
}
parts.push({ text: 'Теперь обведи боксами каждую единицу переднего ряда на ЭТОМ фото по правилам и схеме:' });
// ── MIME целевого фото (№10) ─────────────────────────────────
// Фото может прийти документом: PNG/HEIC/WEBP, а не только JPEG Telegram.
// Приоритет источников: магические байты бинарника → эвристика «Закрепляю тип фотографии» → jpeg.
const MIME_OK = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif']);
let photoMime = null;
try { photoMime = $('Загрузка фото').first().binary.data.mimeType; } catch (e) {}
if (!MIME_OK.has(String(photoMime))) { try { photoMime = $('Закрепляю тип фотографии').first().json.file_mime; } catch (e) {} }
if (!MIME_OK.has(String(photoMime))) photoMime = 'image/jpeg';

const photoB64 = $('Перевод фото в строку').first().json.data;
const photoPart = { inline_data: { mime_type: photoMime, data: photoB64 } };
if (TARGET_MEDIA_RESOLUTION) photoPart.media_resolution = { level: TARGET_MEDIA_RESOLUTION };
parts.push(photoPart);

const gemini_body = {
  systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
  contents: [{ role: 'user', parts }],
  generationConfig: {
    temperature: 0,
    response_mime_type: 'application/json',
    response_schema: RESPONSE_SCHEMA
  }
};
if (MEDIA_RESOLUTION) gemini_body.generationConfig.media_resolution = MEDIA_RESOLUTION;

return [{ json: {
  gemini_body,
  scan_brands: scanBrands,
  refs_count: rows.length,
  refs_variants: rows.filter(r => variantOf(r)).length,
  target_media_resolution: TARGET_MEDIA_RESOLUTION,
  prompt_version: 'v7.4-nopairs-noreven',
  photo_mime: photoMime,                                  // ← №10: чем оказался целевой кадр
  photo_kb: Math.round(photoB64.length * 3 / 4 / 1024),   // ← №10: сколько реально ушло в Gemini
} }];
