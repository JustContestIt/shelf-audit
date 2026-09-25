<!-- imported from the working folder: archive/early_setup_and_prompts/gemini_vision_setup_n8n.md; redactions: 0 -->
# Настройка vision-узла (Gemini 3.5 Flash) в n8n
Проект BURATINO · обновлено 26.06.2026

Этот узел заменяет «мозг» вместо `OCR Google Clous Vision`. Стоит после
`Extract from File` (Base64) и перед разбором ответа.

---

## Шаг 1. API-ключ (бесплатно)
1. Открой **Google AI Studio** → aistudio.google.com
2. *Get API key* → скопируй ключ. Карта не нужна, бесплатный тариф включает Gemini 3.5 Flash
   (лимиты ~15 запросов/мин, ~1500/день).
> Для боевого режима с реальными фото магазинов позже включи биллинг или Vertex AI —
> тогда данные не уходят в обучение Google.

## Шаг 2. Credential в n8n
Credentials → New → **Header Auth**:
- **Name**: `x-goog-api-key`
- **Value**: `<твой ключ>`

(Так ключ не светится в URL и логах.)

## Шаг 3. Нода HTTP Request
- **Method**: `POST`
- **URL**: `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent`
- **Authentication**: Generic Credential Type → **Header Auth** → выбрать credential из шага 2
- **Send Body**: ON → **Body Content Type: JSON**
- В тело вставить JSON ниже.

Где брать Base64: узел `Extract from File` (операция Move File to Base64 String) кладёт
строку в поле `data`. В теле она подставляется через `{{ $json.data }}` — **кавычки оставь**.

### Тело запроса (copy-paste)
```json
{
  "systemInstruction": {
    "parts": [{ "text": "Ты — система визуального аудита выкладки товара на полках. На фото — полка или стойка магазина. Посчитай единицы товара ТОЛЬКО переднего ряда (фейсинги) для брендов: Буратино, AI TEA (если их не видно — все различимые напитки). Правила: считай только единицы переднего ряда, обращённые к камере; НЕ считай товар вглубь полки и скрытый запас; мультипаки и термоупаковку за передним рядом поштучно не считай; каждую переднюю единицу считай один раз; полки нумеруй сверху вниз, верхняя = 1; расположение указывай словами слева/центр/справа; бренд определяй по этикетке, если нечитаемо — product_name 'не определён' и ниже confidence; перед ответом локализуй каждую единицу рамкой. Поле confidence от 0 до 1 — уверенность в точности счёта этой группы. store_name, employee_id и date НЕ указывай — их добавит n8n. Верни строго JSON по заданной схеме, без markdown." }]
  },
  "contents": [{
    "role": "user",
    "parts": [
      { "text": "Посчитай товар на этом фото и верни JSON по схеме." },
      { "inline_data": { "mime_type": "image/jpeg", "data": "{{ $json.data }}" } }
    ]
  }],
  "generationConfig": {
    "temperature": 0,
    "response_mime_type": "application/json",
    "response_schema": {
      "type": "object",
      "properties": {
        "shelves_with_target_product": { "type": "integer" },
        "items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "product_name": { "type": "string" },
              "shelf_index": { "type": "integer" },
              "shelf_location": { "type": "string" },
              "front_facing_count": { "type": "integer" },
              "confidence": { "type": "number" }
            },
            "required": ["product_name", "shelf_index", "shelf_location", "front_facing_count", "confidence"]
          }
        },
        "store_code_on_card": { "type": "string", "nullable": true },
        "overall_confidence": { "type": "number" },
        "notes": { "type": "string" }
      },
      "required": ["shelves_with_target_product", "items", "overall_confidence"]
    }
  },
  "tools": [{ "code_execution": {} }]
}
```

> **code_execution** = agentic vision (модель сама рисует рамки и считает по ним, +5–10% точности).
> Добавляет немного задержки и токенов. Для первого запуска можно убрать блок `"tools"` —
> всё остальное работает так же, просто без бонуса к точности.

## Шаг 4. Разбор ответа (нода Code после HTTP Request)
Gemini кладёт результат в `candidates[0].content.parts`. При включённом code execution
там есть промежуточные части (код/результат), а финальный JSON — в последней текстовой части.

```js
const cand = $input.first().json.candidates?.[0];
const parts = cand?.content?.parts || [];
const textPart = [...parts].reverse().find(p => typeof p.text === 'string');
if (!textPart) {
  throw new Error('Нет текстового ответа Gemini: ' + JSON.stringify($input.first().json).slice(0, 800));
}
const data = JSON.parse(textPart.text);   // чистый JSON, т.к. задана схема
return [{ json: data }];
```

Дальше — узел «массив → строки» (Split Out по `items`) и добавление `store_name`,
`employee_id`, `date` из контекста n8n.

## Шаг 5. Проверка
1. В `Telegram Trigger` нажми *Listen*, отправь боту одно фото полки (или запинь тестовый item).
2. Выполни цепочку до Code-ноды.
3. Убедись, что приходит JSON: непустой `items`, разумные `front_facing_count`,
   заполнен `overall_confidence`. Если `overall_confidence` низкий и `notes` про ракурс —
   это нормально, кадр уйдёт на ручную проверку.

## Заметки
- Размер inline-запроса ≤ 20 МБ. Твои фото ~150–300 КБ — с запасом.
- `temperature: 0` — чтобы счёт был стабильным между запусками.
- Узел `OCR Google Clous Vision` можно отключить или оставить отдельной веткой —
  только для чтения кода магазина с карточки и ценников (текст), не для подсчёта.

## Шаг 6. Если 503 «Service unavailable / high demand» не уходит
Причина: `gemini-3.5-flash` пока в **preview** с ограниченной ёмкостью — при глобальных
спайках спроса 503 прилетает всем сразу, **независимо от тарифа**. Поэтому биллинг сам
по себе эту ошибку может не убрать. По приоритету:

1. **Сменить модель на стабильную GA (самый быстрый фикс).** В URL заменить
   `gemini-3.5-flash` → `gemini-2.5-flash`. Формат запроса и схема те же, но 2.5 Flash —
   зрелая модель и почти не ловит overload. Тестируй на ней сейчас, на 3.5 вернёшься
   позже. (Блок `"tools": [{"code_execution": {}}]` для 2.5 можно убрать.)
2. **Или временно использовать уже подключённые ключи.** В шаблоне есть рабочие
   Anthropic (Claude) и OpenAI (GPT-4o) — обе принимают картинку и вернут JSON. Идеально
   для проверки всего пайплайна, пока Gemini недоступен. Точность счёта чуть ниже.
3. **Авто-ретрай.** HTTP Request → Settings: `Retry On Fail` ON, `Max Tries` 4–5,
   `Wait Between Tries` 3000–5000 мс.
4. **Не частить** при пакетной обработке: узел `Wait` ~4–5 с внутри `Loop Over Items`
   или Batch API.
5. **Биллинг** — нужен для высоких рейт-лимитов и боевой/пакетной нагрузки, но от 503 на
   preview-модели не панацея. Подключение: AI Studio → **Billing** → *Set up billing* на
   проекте; с марта 2026 обычно просят предоплату от **$10** (план Prepay).

Для живого Telegram (по одному фото) хватает п.1 + п.3.

## Шаг 7. Справочник брендов (few-shot) + борьба с недосчётом
Готовый справочник: `Brands/brand_catalog.png` — 5 брендов с подписями. Подаём его в запрос
ПЕРЕД целевым фото: модель сверяется и узнаёт даже редкие бренды (например Tamga, Chinò).

Бренды для подсчёта (обнови в системном промпте): **Буратино, AI TEA, Chinò, Компотай, Tamga**.

### Как подключить (parts)
```json
"contents": [{
  "role": "user",
  "parts": [
    { "text": "Это СПРАВОЧНИК БРЕНДОВ компании. На фото полки считать нужно только эти бренды: Буратино, AI TEA, Chinò, Компотай, Tamga. Сверяйся с ним при распознавании:" },
    { "inline_data": { "mime_type": "image/png", "data": "{{ $json.catalog_b64 }}" } },
    { "text": "Теперь проанализируй ЭТО фото полки и посчитай по правилам и схеме:" },
    { "inline_data": { "mime_type": "image/jpeg", "data": "{{ $json.data }}" } }
  ]
}]
```

### Откуда брать base64 каталога — два варианта
- **Просто (для теста):** прямо перед HTTP Request поставь узел Set, добавь поле
  `catalog_b64` = строка из `Brands/brand_catalog.b64.txt`, включи **Include Other Input
  Fields**, и ссылайся через `{{ $json.catalog_b64 }}`. Каталог едет с каждым запросом.
- **Боевой (дёшево):** загрузи каталог один раз через **Files API**, получи `file_uri`,
  и включи **context caching** — справочник хранится на стороне Google, запросы лишь
  ссылаются на кэш. Кэшированный вход дешевле (~$0.15 за 1М токенов) и быстрее.

### Против недосчёта — правка промпта
Добавь в системный промпт: «Считай отдельно по каждой полке. На каждой полке перечисляй
единицы переднего ряда слева направо и считай поштучно, не оценивай число на глаз; не
пропускай частично видимые с краёв единицы». Перечисление надёжнее, чем «прикинь число».
