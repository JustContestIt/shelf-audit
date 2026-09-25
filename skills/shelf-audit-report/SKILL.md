---
name: shelf-audit-report
description: Build the customer's shelf-audit report (xlsx) for a store, a route or a day from the shelf-audit MCP server. Use when the user asks for «аудит полки», «сводка по магазину», «сводка по маршруту», «отчёт по фейсингам», «сколько наших бутылок в магазине», «выгрузи отчёт заказчику», facings / shelf share of Буратино, AI TEA, Chino, Компотай, Tamga. Not for questions about the pipeline code, prompts or evals.
---

# Shelf audit report

Turns audited shelf photos into the customer's report: facings per store × brand × subtype × pack,
in the xlsx layout the customer already uses (sheet «Данные» with atomic rows + sheet «Сводка»).

## Before you start

Needs the `shelf-audit-mcp` server connected (tools `get_store_report`, `list_pending_reviews`,
`analyze_shelf_photo`, `search_catalog`). If the tools are missing, say so and stop — do not make
numbers up.

## Procedure

1. **Scope.** Find out the store code(s) or the day. «По маршруту» = all stores of the route: ask for
   the store codes if the user did not give them (the route sheet lives in the customer's system).
2. **Pending work.** Call `list_pending_reviews` for the scope. If there are reports waiting for a
   supervisor, tell the user how many and give their review links: those units are not in the report yet.
3. **Data.** For every store call `get_store_report(store_code, day)`. Use `include_pending=true` only if
   the user explicitly wants a draft — and then say so in the answer and in the file name.
4. **Apply the rules** from `references/report_rules.md` — the important ones:
   - only front-row facings are counted (the pipeline already does this);
   - competitors are never counted: foreign units = 0 in the report, always;
   - rows with `needs_review_count > 0` go to a separate sheet «На проверку», not into the totals;
   - a missing subtype is written as «не опознано», never guessed from neighbours.
5. **Export.** Save the tool results as JSON (one list of `get_store_report` outputs) and run
   `python scripts/export_report.py --input <that.json> --out <report.xlsx>`.
   The script writes «Данные», «Сводка» (SUMIFS formulas, as in the customer's example) and «На проверку».
6. **Answer** with: the file, total facings per brand, the number of units still under review, and the
   stores without any approved report. Keep it to a few lines; the numbers are in the file.

## When the user sends a photo instead

Call `analyze_shelf_photo` (it takes 1–2 minutes). Show the counts by shelf and the review link;
remind that the report becomes final only after a supervisor approves it. Shooting advice for the
agent: `references/photo_rules.md`.

## Files

- `scripts/export_report.py` — JSON (get_store_report outputs) -> xlsx in the customer's format.
- `references/report_rules.md` — counting rules and the column schema.
- `references/photo_rules.md` — how agents must photograph a shelf (for «почему не посчитал?» answers).
