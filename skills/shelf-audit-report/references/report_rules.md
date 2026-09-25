# Counting rules and report schema

## What is counted
- **Front-row facings only.** One physical bottle/can facing the camera = 1. Stock behind, multipacks
  in the background and other racks separated by a frame/wall/aisle are not counted.
- **Partially visible units at the frame edge are counted** (production rule since 27.07).
- **Competitors are never counted.** Units the model marks ЧУЖОЙ, and units the SigLIP check finds unlike
  any of our reference images, stay out of the totals. Contamination in the report must be 0.
- **Subtype.** Canon names only (22 SKUs: `AI TEA малина`, `Буратино классический`, `Компотай вишневый`…).
  Tamga has no subtypes. A unit without a confident subtype is «не опознано» — not the neighbour's name.
- **Pack.** `банка 0,45 л`, `банка 0,9 л`, `ПЭТ 0,25 / 0,5 / 1 / 1,5 / 2 / 2,4 л`; Chino and Tamga have no pack.
  Big PET (1 / 1,5 / 2 л) is arbitrated by geometry (width relative to the 0,45 can on the same frame).
- **needs_review.** A row is not final while a supervisor has not confirmed it: pass 2 was unsure,
  the subtype is unknown, or the unit looks like a competitor. Report such rows separately.

## Sheet «Данные» (one row = one brand × subtype × pack on one shelf of one photo)

| column | meaning |
|---|---|
| report_id | one photo = one report |
| report_date | date of the photo (Asia/Almaty, UTC+5) |
| route_code | route of the agent (1 route = 1 agent) |
| store_code | store code from the customer's system (00-0007xxx) |
| store_name | store name |
| product_name | brand |
| product_subtype | canon subtype or «не опознано» |
| package_format | pack |
| shelf_index | 1 = top shelf |
| position | слева / центр / справа (by the mean x of the units) |
| front_facing_count | facings |
| status | утверждено / исправлено (на_проверке only in drafts) |

## Sheet «Сводка»
Per store × brand: total facings (`SUMIFS` over «Данные») and the number of shelves with the brand —
the same formulas as the customer's `structure_example_buratino.xlsx`.
