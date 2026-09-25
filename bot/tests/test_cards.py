from shelf_bot.cards import progress_text, report_card, review_keyboard, stores_keyboard

REP = {"report_id": "R_1", "status": "awaiting_review", "store_name": "Демо-точка 1",
       "body": {"report": {"total_units": 13, "needs_review_units": 2, "foreign_units": 5, "low_confidence": False, "rows": [
           {"shelf_index": 1, "brand": "AI TEA", "subtype": "AI TEA малина", "package_format": "банка 0,45 л", "front_facing_count": 2,
            "needs_review": True},
           {"shelf_index": 1, "brand": "Tamga", "subtype": None, "package_format": None, "front_facing_count": 1},
           {"shelf_index": 2, "brand": "Буратино", "subtype": None, "package_format": "ПЭТ 1,5 л", "front_facing_count": 10,
            "needs_review": True}]}}}


def test_card_texts():
    t = report_card(REP)
    assert "Полка 1" in t and "Полка 2" in t
    assert "AI TEA малина, банка 0,45 л — <b>2</b> ⚠️" in t
    assert "Tamga —" in t and "Буратино не опознано" in t
    assert "Чужой товар рядом (не в счёте): 5" in t and "всё верно?" in t
    assert "⛔" in report_card({"status": "rejected", "reject_reason": "фото смазано", "body": {}})
    assert "✅ Утверждено" in report_card({**REP, "status": "approved"})


def test_keyboards():
    kb = review_keyboard("R_1")
    assert [b.callback_data for b in kb.inline_keyboard[0]] == ["approve:R_1", "retake:R_1"]
    stores = [{"store_code": f"S{i}", "store_name": f"Магазин {i}", "address": "ул. 1"} for i in range(19)]
    k0 = stores_keyboard(stores, 0)
    assert len(k0.inline_keyboard) == 9 and k0.inline_keyboard[-1][1].text == "1 / 3"
    assert k0.inline_keyboard[-1][0].callback_data == "noop"  # no page before the first
    k2 = stores_keyboard(stores, 5)  # clamped to the last page
    assert k2.inline_keyboard[-1][1].text == "3 / 3" and len(k2.inline_keyboard) == 4
    assert progress_text({"progress": [{"node": "verify_subtypes"}]}) == "⏳ уточняю вкусы…"
