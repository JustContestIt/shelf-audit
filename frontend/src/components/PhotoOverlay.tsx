import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { DetectedBox, PhotoMeta, ReportRow } from '../api/types';
import { FOREIGN_COLOR, NEUTRAL_COLOR, SLIVER_COLOR, colorForSubtype, legendFor } from '../lib/colors';
import { isForeign, isUnknownSubtype } from '../lib/domain';
import { fmtPercent } from '../lib/format';
import { scaleBox } from '../lib/geometry';
import { normShelf } from '../lib/match';

interface Props {
  src: string | null;
  boxes: DetectedBox[];
  slivers: DetectedBox[];
  rows: ReportRow[];
  /** report-row index for every box (-1 = none), from matchBoxesToRows */
  matches: number[];
  selectedRow: number | null;
  onSelectRow: (row: number | null) => void;
  photo?: PhotoMeta;
  /** the supervisor edited the rows: boxes still show the model's original labels */
  edited?: boolean;
}

type Hover = { kind: 'box' | 'sliver'; index: number } | null;

const REVIEW_DASH = '7 4';
const FOREIGN_DASH = '1.5 3';

function Tooltip({
  box,
  kind,
  row,
  left,
  top,
  above,
}: {
  box: DetectedBox;
  kind: 'box' | 'sliver';
  row: ReportRow | undefined;
  left: number;
  top: number;
  above: boolean;
}) {
  const foreign = isForeign(box.label);
  const shelf = normShelf(box.shelf_index);
  const noSubtypeText = row && !isUnknownSubtype(row) ? '—' : 'не опознано';
  return (
    <div
      className="box-tip"
      style={{ left, top, transform: above ? 'translate(-50%, calc(-100% - 8px))' : 'translate(-50%, 8px)' }}
      role="tooltip"
    >
      {kind === 'sliver' && <div className="tip-warn">Щепка — отсеяна как слишком узкая</div>}
      <div>
        <b>Полка:</b> {shelf || 'не определена'}
      </div>
      <div>
        <b>Бренд:</b> {foreign ? 'чужой товар (не в счёте)' : box.label}
      </div>
      {!foreign && (
        <div>
          <b>Подвид:</b> {box.subtype || noSubtypeText}
        </div>
      )}
      <div>
        <b>Тара:</b> {box.format || '—'}
      </div>
      <div>
        <b>Уверенность:</b> {fmtPercent(box.confidence ?? null)}
      </div>
      {row?.needs_review && (
        <div className="tip-warn">⚠ На проверку{row.review_reason ? `: ${row.review_reason}` : ''}</div>
      )}
    </div>
  );
}

function LegendSwatch({ color, dash, cross, thin }: { color: string; dash?: string; cross?: boolean; thin?: boolean }) {
  return (
    <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden="true" focusable="false">
      <rect x="1.5" y="1.5" width="19" height="11" rx="1" fill="none" stroke="rgba(0,0,0,.45)" strokeWidth={thin ? 2.5 : 4} />
      <rect x="1.5" y="1.5" width="19" height="11" rx="1" fill={color} fillOpacity={0.15} stroke={color} strokeWidth={thin ? 1 : 2} strokeDasharray={dash} />
      {cross && <path d="M8 4l6 6M14 4l-6 6" stroke={color} strokeWidth="1.6" />}
    </svg>
  );
}

/** The shelf photo with an SVG overlay of the detected boxes, scaled to the displayed image size. */
export function PhotoOverlay({ src, boxes, slivers, rows, matches, selectedRow, onSelectRow, photo, edited }: Props) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [failed, setFailed] = useState(false);
  const [showSlivers, setShowSlivers] = useState(false);
  const [hover, setHover] = useState<Hover>(null);
  const [orientationMismatch, setOrientationMismatch] = useState(false);

  // a new photo (retake) gets a fresh chance to load
  useEffect(() => {
    setFailed(false);
    setOrientationMismatch(false);
  }, [src]);

  const measure = useCallback(() => {
    const img = imgRef.current;
    if (!img) return;
    setSize((s) => (s.w === img.clientWidth && s.h === img.clientHeight ? s : { w: img.clientWidth, h: img.clientHeight }));
  }, []);

  // keep the overlay glued to the image on window / layout resize
  useLayoutEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(img);
    return () => ro.disconnect();
  }, [src, failed, measure]);

  const onLoad = () => {
    measure();
    const img = imgRef.current;
    if (img && photo && photo.width > 0 && photo.height > 0) {
      const shownLandscape = img.naturalWidth >= img.naturalHeight;
      const analysedLandscape = photo.width >= photo.height;
      setOrientationMismatch(shownLandscape !== analysedLandscape);
    }
  };

  const legend = useMemo(() => legendFor(boxes), [boxes]);
  const foreignCount = useMemo(() => boxes.filter((b) => isForeign(b.label)).length, [boxes]);
  const reviewCount = useMemo(
    () => boxes.filter((_, i) => matches[i] >= 0 && rows[matches[i]]?.needs_review).length,
    [boxes, matches, rows],
  );

  const { w, h } = size;
  const ready = w > 0 && h > 0 && !failed;

  // draw competitors first, then ours, the selected row on top
  const order = useMemo(() => {
    const idx = boxes.map((_, i) => i);
    const rank = (i: number) => (isForeign(boxes[i].label) ? 0 : matches[i] === selectedRow && selectedRow !== null ? 2 : 1);
    return idx.sort((a, b) => rank(a) - rank(b));
  }, [boxes, matches, selectedRow]);

  const hovered = hover ? (hover.kind === 'box' ? boxes[hover.index] : slivers[hover.index]) : undefined;
  let tip: { left: number; top: number; above: boolean } | null = null;
  if (hovered && ready) {
    const r = scaleBox(hovered.box_2d, w, h);
    const above = r.y + r.height + 130 > h && r.y > 130;
    // the tooltip is at most min(260px, 90%) wide: keep its centre far enough from both edges
    const half = Math.min(130, w * 0.45) + 4;
    tip = {
      left: Math.min(Math.max(r.x + r.width / 2, half), Math.max(half, w - half)),
      top: above ? r.y : r.y + r.height,
      above,
    };
  }

  return (
    <div>
      <div className="photo-frame">
        {src && !failed ? (
          <div className="photo-stage" onMouseLeave={() => setHover(null)}>
            <img
              ref={imgRef}
              src={src}
              alt="Фото полки"
              onLoad={onLoad}
              onError={() => setFailed(true)}
              draggable={false}
            />
            {ready && (
              <svg
                className="overlay"
                width={w}
                height={h}
                viewBox={`0 0 ${w} ${h}`}
                role="img"
                aria-label={`Рамки товаров: ${boxes.length - foreignCount} наших, ${foreignCount} чужих`}
              >
                {order.map((i) => {
                  const b = boxes[i];
                  const r = scaleBox(b.box_2d, w, h);
                  const foreign = isForeign(b.label);
                  const rowIdx = matches[i];
                  const row = rowIdx >= 0 ? rows[rowIdx] : undefined;
                  const selected = selectedRow !== null && rowIdx === selectedRow;
                  const dimmed = selectedRow !== null && !selected;
                  const color = foreign ? FOREIGN_COLOR : colorForSubtype(b.subtype);
                  const sw = selected ? 3.5 : 2;
                  const dash = foreign ? FOREIGN_DASH : row?.needs_review ? REVIEW_DASH : undefined;
                  const cross = Math.min(9, r.width * 0.4, r.height * 0.4);
                  return (
                    <g
                      key={i}
                      opacity={dimmed ? 0.28 : 1}
                      className={rowIdx >= 0 ? 'hit' : undefined}
                      onMouseEnter={() => setHover({ kind: 'box', index: i })}
                      onClick={() => rowIdx >= 0 && onSelectRow(selected ? null : rowIdx)}
                    >
                      <rect
                        x={r.x}
                        y={r.y}
                        width={r.width}
                        height={r.height}
                        fill="none"
                        stroke="rgba(0,0,0,0.55)"
                        strokeWidth={sw + 2.5}
                        pointerEvents="none"
                      />
                      <rect
                        x={r.x}
                        y={r.y}
                        width={r.width}
                        height={r.height}
                        fill={color}
                        fillOpacity={selected ? 0.22 : foreign ? 0.04 : 0.08}
                        stroke={color}
                        strokeWidth={sw}
                        strokeDasharray={dash}
                      />
                      {foreign && cross > 2 && (
                        <path
                          d={`M${r.x + 3} ${r.y + 3}l${cross} ${cross}M${r.x + 3 + cross} ${r.y + 3}l${-cross} ${cross}`}
                          stroke={FOREIGN_COLOR}
                          strokeWidth={1.8}
                          pointerEvents="none"
                        />
                      )}
                    </g>
                  );
                })}
                {showSlivers &&
                  slivers.map((b, i) => {
                    const r = scaleBox(b.box_2d, w, h);
                    return (
                      <rect
                        key={`s${i}`}
                        x={r.x}
                        y={r.y}
                        width={Math.max(r.width, 1)}
                        height={r.height}
                        fill={SLIVER_COLOR}
                        fillOpacity={0.12}
                        stroke={SLIVER_COLOR}
                        strokeWidth={1}
                        onMouseEnter={() => setHover({ kind: 'sliver', index: i })}
                      />
                    );
                  })}
              </svg>
            )}
            {hovered && tip && (
              <Tooltip
                box={hovered}
                kind={hover!.kind}
                row={hover!.kind === 'box' && matches[hover!.index] >= 0 ? rows[matches[hover!.index]] : undefined}
                {...tip}
              />
            )}
          </div>
        ) : (
          <div className="photo-missing">{src ? 'Фото недоступно' : 'Фото нет'}</div>
        )}
      </div>

      <div className="photo-tools">
        <label className="check small">
          <input
            type="checkbox"
            checked={showSlivers}
            onChange={(e) => setShowSlivers(e.target.checked)}
            disabled={slivers.length === 0}
          />
          Показать отсеянные (щепки){slivers.length ? ` — ${slivers.length}` : ' — нет'}
        </label>
        {selectedRow !== null && (
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => onSelectRow(null)}>
            Снять выделение
          </button>
        )}
      </div>

      {orientationMismatch && (
        <p className="hint" role="note">
          Ориентация показанного фото отличается от анализировавшейся ({photo?.width}×{photo?.height}) — рамки могут не
          совпадать.
        </p>
      )}
      {edited && (
        <p className="hint" role="note">
          Рамки показывают исходную разметку модели; правки супервайзера отражены в таблице.
        </p>
      )}

      <ul className="legend" aria-label="Легенда">
        {legend.map((l) => (
          <li key={l.subtype ?? '∅'}>
            <LegendSwatch color={l.color} />
            {l.subtype ?? 'без подвида'} <span className="count">×{l.count}</span>
          </li>
        ))}
        <li className="legend-sep" aria-hidden="true" />
        <li>
          <LegendSwatch color={NEUTRAL_COLOR} dash={REVIEW_DASH} />
          пунктир — на проверку{reviewCount ? ` (${reviewCount})` : ''}
        </li>
        <li>
          <LegendSwatch color={FOREIGN_COLOR} dash={FOREIGN_DASH} cross />
          чужой, не в счёте{foreignCount ? ` (${foreignCount})` : ''}
        </li>
        {slivers.length > 0 && (
          <li>
            <LegendSwatch color={SLIVER_COLOR} thin />
            щепка (отсеяна)
          </li>
        )}
      </ul>
    </div>
  );
}
