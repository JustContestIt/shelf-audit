#!/usr/bin/env python3
"""Скорер прогонов по кадру IMG_0644 (5 полок, gt 53 юнита).

Вход: TSV прогона из runs/ (см. формат в шапке файлов) — боксы в шкале 0..1000,
      строки '#' игнорируются.
Эталон: gt_IMG_0644.json (боксы YOLO11x + вкусы из эмбеддинг-эксперимента,
      счёт полок — настоящий gt замеров 11/11/11/10/10).

Метрики:
  COUNT      — счёт по полкам против gt замеров (то, что уходит в Excel заказчику)
  LOCALIZE   — матчинг боксов с gt-боксами по IoU (жадный, порог 0.4)
  SUBTYPE    — точность вкуса на сматченных юнитах
  FORMAT     — точность тары на сматченных юнитах
Пример: python3 score_0644.py runs/qwen3vl_OR_0644_r1.tsv
"""
import sys, json, collections, os

SHORT = {  # короткое имя -> каноническое
 'помело':'помело-цветок апельсина','гуава':'гуава-тропики','манго':'манго-маракуйя',
 'клубника':'клубника-киви','лимон':'лимон-лайм-жасмин','малина':'малина',
 'персик':'персик-жасмин','мандарин':'мандарин-лаванда','ревень':'ревень',
}
def canon(s):
    s = s.strip().replace('AI TEA ','')
    return SHORT.get(s, s)

def short(s):
    for k,v in SHORT.items():
        if v == s: return k
    return s

def iou(a, b):
    ax1,ay1,ax2,ay2 = a; bx1,by1,bx2,by2 = b
    ix1,iy1 = max(ax1,bx1), max(ay1,by1)
    ix2,iy2 = min(ax2,bx2), min(ay2,by2)
    iw,ih = max(0,ix2-ix1), max(0,iy2-iy1)
    inter = iw*ih
    if inter == 0: return 0.0
    ua = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter/ua

def load_run(path):
    meta, rows = {}, []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if line.startswith('#'):
            for kv in line.lstrip('# ').split('\t'):
                if '=' in kv:
                    k,v = kv.split('=',1); meta[k.strip()] = v.strip()
            continue
        if not line.strip(): continue
        p = line.split('\t')
        rows.append({'shelf':int(p[0]),
                     'box':[int(p[2]),int(p[1]),int(p[4]),int(p[3])],  # -> x1,y1,x2,y2
                     'subtype':canon(p[5]), 'format':p[6].strip()})
    return meta, rows

def main(path):
    gt = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'gt_IMG_0644.json'), encoding='utf-8'))
    W,H = gt['width'], gt['height']
    gtu = [dict(u, box=u['box_xyxy']) for u in gt['units']]
    meta, run = load_run(path)
    for r in run:  # 0..1000 -> пиксели
        x1,y1,x2,y2 = r['box']
        r['box'] = [x1*W/1000, y1*H/1000, x2*W/1000, y2*H/1000]

    print(f"\n=== {os.path.basename(path)} ===")
    for k,v in meta.items(): print(f"  {k} = {v}")

    # ---- COUNT ----
    cnt = collections.Counter(r['shelf'] for r in run)
    gtc = {int(k):v for k,v in gt['shelf_counts_gt'].items()}
    print("\n[COUNT] полка: модель / gt")
    ok = 0
    for s in sorted(gtc):
        d = cnt.get(s,0) - gtc[s]
        ok += min(cnt.get(s,0), gtc[s])
        print(f"   {s}: {cnt.get(s,0):>3} / {gtc[s]:<3} {'' if d==0 else f'  <-- {d:+d}'}")
    print(f"   ИТОГО: {sum(cnt.values())} / {gt['total_gt']}   счёт-точность {ok}/{gt['total_gt']}")

    # ---- LOCALIZE (жадный матчинг по IoU) ----
    pairs = sorted(((iou(r['box'],g['box']), i, j) for i,r in enumerate(run)
                    for j,g in enumerate(gtu) if iou(r['box'],g['box']) > 0.4),
                   reverse=True)
    ur, ug, m = set(), set(), []
    for v,i,j in pairs:
        if i in ur or j in ug: continue
        ur.add(i); ug.add(j); m.append((v,i,j))
    print(f"\n[LOCALIZE] IoU>0.4: сматчено {len(m)}/{len(gtu)} gt-боксов; "
          f"боксов модели без пары {len(run)-len(m)}; средний IoU {sum(v for v,_,_ in m)/max(1,len(m)):.2f}")

    # ---- SUBTYPE / FORMAT / SHELF ----
    sub_ok = fmt_ok = sh_ok = 0
    err = collections.Counter()
    for v,i,j in m:
        r,g = run[i], gtu[j]
        if r['subtype'] == g['subtype']: sub_ok += 1
        else: err[(short(g['subtype']), short(r['subtype']), g['shelf'], g['format'])] += 1
        if r['format'] == g['format']: fmt_ok += 1
        if r['shelf'] == g['shelf']: sh_ok += 1
    n = len(m)
    print(f"[SUBTYPE]  {sub_ok}/{n} ({100*sub_ok/max(1,n):.1f}%)")
    print(f"[FORMAT]   {fmt_ok}/{n}")
    print(f"[SHELF]    {sh_ok}/{n}")
    if err:
        print("\n[ОШИБКИ ВКУСА]  gt -> модель  (полка, тара) xN")
        for (a,b,s,f),c in err.most_common():
            print(f"   {a} -> {b}   (полка {s}, {f}) x{c}")
    print()

if __name__ == '__main__':
    for p in sys.argv[1:]: main(p)
