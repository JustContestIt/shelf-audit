# Trigger check (Phase 4: «срабатывание на 4–5 формулировках и несрабатывание на чужих»)

Run each phrase in Claude Desktop with the skill installed and the MCP server connected; tick what happened.

| # | phrase | expected | result |
|---|---|---|---|
| 1 | «Сделай сводку по магазину 00-0000001 за сегодня» | skill loads, `get_store_report`, xlsx | |
| 2 | «Аудит полки по маршруту 000000001» | skill loads, asks for store codes / uses route | |
| 3 | «Сколько наших бутылок AI TEA в Демо-точке 2?» | skill loads, `get_store_report` | |
| 4 | «Выгрузи отчёт по фейсингам для заказчика» | skill loads, asks scope, xlsx | |
| 5 | «Вот фото полки, посчитай» (+ photo) | `analyze_shelf_photo`, review link | |
| 6 | «Почему проход 2 ухудшает подвиды?» | skill does NOT load (question about the pipeline) | |
| 7 | «Напиши SQL для таблицы reports» | skill does NOT load | |
| 8 | «Какая погода в Алматы?» | skill does NOT load | |

Demo script (Demo Day): 1 → open the xlsx («Сводка» with formulas) → 5 with IMG_0644 → open the review link.
