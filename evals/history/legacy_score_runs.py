#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скорер прогонов BURATINO. Кладёшь экспорты в bench/runs/*.txt — запускаешь:
    python3 bench/score_runs.py
Формат файла прогона: шапка (одна строка, необязательна) + блоки "PASS 1:" и "PASS 2:" с JSON.
Считает ошибки подвида по ПОЗИЦИЯМ (боксы сортируются по x внутри полки), отдельно
проход 1 и финал, ловит дубли прогонов и печатает сводку с разбросом.
"""
import json, re, sys, os, glob, statistics, itertools

BASE = os.path.dirname(os.path.abspath(__file__))
GT = json.load(open(os.path.join(BASE, 'GT_aitea_5shelf.json'), encoding='utf-8'))
LONG2SHORT = {v: k for k, v in GT['aliases'].items()}
TRUTH = {int(k): v for k, v in GT['shelves'].items()}


def _norm(o):
    """Приводит слепок ноды-сборщика (detect/usage/pass2) к виду прогона (_detect/_usage/_pass2)."""
    if not o: return None
    if '_detect' in o or '_usage' in o: return o
    d = o.get('detect') or {}
    det = dict(d)
    if 'anchor' in det: det['format_geo'] = {'anchor': det.get('anchor')}
    return {'_detect': det, '_usage': o.get('usage') or {}, '_pass2': o.get('pass2')}

def _parse(chunk):
    """Берёт первый JSON-объект/массив из куска текста, хвост игнорирует."""
    m = re.search(r'[\[{]', chunk)
    if not m: return None
    o, _ = json.JSONDecoder().raw_decode(chunk[m.start():])
    return o[0] if isinstance(o, list) and o else o

def load(path):
    """-> (шапка, (проход1, проход2)). Понимает и текстовые блоки PASS, и слепок _bench."""
    t = open(path, encoding='utf-8').read()

    # формат ноды-сборщика: [{ "_bench": { run, ts, frame, pass1, pass2 } }]
    if '"_bench"' in t:
        o = _parse(t)
        b = (o or {}).get('_bench') or {}
        head = ' | '.join(str(b.get(k, '')) for k in ('run', 'ts', 'frame') if b.get(k))
        return head, (_norm(b.get('pass1')), _norm(b.get('pass2')))

    marks = [(m.start(), m.end(), int(m.group(1))) for m in re.finditer(r'PASS\s*([12])\s*:', t)]
    if not marks:
        o = _parse(t)
        return '', ((None, o) if o and '_pass2' in o else (o, None))
    head = t[:marks[0][0]].strip()
    head = head.splitlines()[-1] if head else ''
    js = {}
    for i, (s, e, n) in enumerate(marks):
        chunk = t[e: marks[i + 1][0] if i + 1 < len(marks) else len(t)]
        try:
            js[n] = _parse(chunk)
        except Exception as ex:
            print(f'!! {path}: блок PASS {n} не разобрался ({ex})')
    return head, (js.get(1), js.get(2))

def _best_align(bs, exp, tag):
    """Подгоняет боксы к слотам эталона. Если боксов меньше — перебирает, какие слоты
    пропущены (фильтр слайверов, перекрытые бутылки), и берёт вариант с минимумом ошибок."""
    if len(bs) == len(exp):
        return list(zip(bs, exp)), 0
    k = len(exp) - len(bs)
    if k <= 0 or k > 2:
        return None, k
    best = None
    for drop in itertools.combinations(range(len(exp)), k):
        sub = [e for i, e in enumerate(exp) if i not in drop]
        e = sum(1 for b, x in zip(bs, sub)
                if ('ЧУЖОЙ' if b.get('label') == 'ЧУЖОЙ' else LONG2SHORT.get(b.get('subtype'), '—')) != x)
        if best is None or e < best[1]:
            best = (list(zip(bs, sub)), e)
    return best[0], k


def score(o):
    """-> (ошибок подвида, всего своих единиц, чужих_втянуто, список замечаний)

    Выравнивание по позициям внутри полки:
      * боксов == слотов эталона  -> 1:1 (модель разметила и чужие);
      * боксов == своих слотов    -> чужие не размечены (норма);
      * боксов меньше на 1–2      -> подбор пропущенных слотов, потеря считается отдельно;
      * иначе                     -> позиции не сверить.
    """
    if not o or '_detect' not in o: return None
    by = {}
    for b in o['_detect'].get('boxes_raw', []):
        by.setdefault(b.get('shelf_index'), []).append(b)
    err = tot = frn = 0; bad = []; unaligned = False
    for sh in sorted(k for k in by if k in TRUTH):
        bs = sorted(by[sh], key=lambda b: b['box_2d'][1])
        exp = TRUTH[sh]
        own = [e for e in exp if e != 'ЧУЖОЙ']
        base = exp if len(bs) >= len(exp) else (exp if len(bs) == len(exp) else own)
        if len(bs) == len(exp):
            pairs, lost = list(zip(bs, exp)), 0
        else:
            pairs, lost = _best_align(bs, own, sh)
            if pairs is not None and len(own) != len(exp):
                bad.append(f"П{sh}: чужие банки не размечены — ок")
        if pairs is None:
            bad.append(f"П{sh}: боксов {len(bs)}, ожидалось {len(exp)} (со своими {len(own)}) — позиции не сверить")
            unaligned = True
            continue
        if lost:
            bad.append(f"П{sh}: ПОТЕРЯНО единиц: {lost} (фильтр слайверов / перекрытие)")
        for i, (b, e) in enumerate(pairs, 1):
            got = 'ЧУЖОЙ' if b.get('label') == 'ЧУЖОЙ' else LONG2SHORT.get(b.get('subtype'), '—')
            if e == 'ЧУЖОЙ':
                if got != 'ЧУЖОЙ':
                    frn += 1; bad.append(f"П{sh}.{i}: чужая → {got}")
                continue
            tot += 1
            if got != e:
                err += 1; bad.append(f"П{sh}.{i}: {e} → {got}")
    return (None if unaligned else err), tot, frn, bad

def sig(o):
    if not o or '_detect' not in o: return None
    return json.dumps([[b['box_2d'], b.get('label'), b.get('subtype')] for b in o['_detect'].get('boxes_raw', [])],
                      ensure_ascii=False, sort_keys=True)

def main(pattern=None):
    if pattern:
        files = sorted(glob.glob(pattern, recursive=True))
    else:
        files = sorted(glob.glob(os.path.join(BASE, 'runs', '**', '*.txt'), recursive=True))
    if not files:
        print('нет файлов в bench/runs/'); return
    rows, seen = [], {}
    for f in files:
        head, (p1, p2) = load(f)
        s1, s2 = score(p1), score(p2)
        u1 = (p1 or {}).get('_usage', {})
        pu = (p2 or {}).get('_pass2', {}) or {}
        k = sig(p1)
        dup = seen.get(k) if k else None
        if k: seen.setdefault(k, os.path.basename(f))
        grp = os.path.relpath(os.path.dirname(f), os.path.join(BASE, 'runs'))
        rows.append(dict(f=(grp + '/' if grp not in ('.', '') else '') + os.path.basename(f), grp=grp, head=head, s1=s1, s2=s2, u1=u1, pu=pu, dup=dup,
                         anchor=((p1 or {}).get('_detect', {}) or {}).get('format_geo', {}).get('anchor')))
    w = max(len(r['f']) for r in rows) + 1
    print(f"{'файл'.ljust(w)} {'п1 ош':>6} {'финал':>6} {'чужих':>6} {'changed':>8} {'nrev':>5} {'out_tok':>8}  anchor")
    print('-' * (w + 60))
    for r in rows:
        e1 = (r['s1'][0] if r['s1'] and r['s1'][0] is not None else 'н/д') if r['s1'] else '?'; f1 = r['s1'][2] if r['s1'] else '?'
        e2 = (r['s2'][0] if r['s2'] and r['s2'][0] is not None else 'н/д') if r['s2'] else '?'
        a = r['anchor'] or {}
        print(f"{r['f'].ljust(w)} {str(e1):>6} {str(e2):>6} {str(f1):>6} "
              f"{str(r['pu'].get('subtypes_changed','')):>8} {str(r['pu'].get('needs_review','')):>5} "
              f"{str(r['u1'].get('output_tokens','')):>8}  cans={a.get('cans')} w_rel={a.get('w_rel')}"
              + (f"   ↺ тот же ответ прохода 1, что и в {r['dup']}" if r['dup'] else ''))
    groups = {}
    for r in rows: groups.setdefault(r['grp'], []).append(r)
    ok1 = [r['s1'][0] for r in rows if r['s1'] and r['s1'][0] is not None and not r['dup']]
    ok2 = [r['s2'][0] for r in rows if r['s2'] and r['s2'][0] is not None]
    def st(v):
        if not v: return '—'
        return f"мин {min(v)} / медиана {statistics.median(v):g} / макс {max(v)}" + (f", σ={statistics.stdev(v):.1f}" if len(v) > 1 else '')
    print(f"\nПроход 1 (уникальных ответов, n={len(ok1)}): {st(ok1)}")
    print("   ↺ = проход 1 повторил ответ другого прогона. Сверь id выполнения: если они разные,\n       это не копипаста, а детерминизм прохода 1 — и разброс идёт из прохода 2.")
    print(f"Финал      (n={len(ok2)}): {st(ok2)}")
    print(f"Всего своих единиц в кадре: {sum(1 for s in TRUTH.values() for x in s if x != 'ЧУЖОЙ')}, чужих: {sum(1 for s in TRUTH.values() for x in s if x == 'ЧУЖОЙ')}")
    for r in rows:
        if r['s2'] and r['s2'][3]:
            print(f"\n— {r['f']}  {r['head']}")
            for b in r['s2'][3]: print('   ', b)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
