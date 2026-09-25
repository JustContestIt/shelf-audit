import type { DetectedBox } from '../api/types';
import { isForeign } from './domain';

/** Boxes of a brand without a subtype (or with an unrecognised one). */
export const NEUTRAL_COLOR = '#eef2f7';
/** Competitor («ЧУЖОЙ») boxes. */
export const FOREIGN_COLOR = '#9aa3af';
/** Boxes dropped by post-processing as too narrow («щепки»). */
export const SLIVER_COLOR = '#ef4444';

/**
 * Fixed colours for the known canon names. AI TEA colours follow the label background
 * (малина — фиолетовый, гуава — зелёный …) but are spread apart so that neighbours on a
 * shelf — especially the «pink zone» ревень / персик — never share a colour.
 */
export const KNOWN_SUBTYPE_COLORS: Readonly<Record<string, string>> = {
  'AI TEA малина': '#8b3fd9',
  'AI TEA гуава-тропики': '#1f9d55',
  'AI TEA помело-цветок апельсина': '#9bd11e',
  'AI TEA мандарин-лаванда': '#f26b1d',
  'AI TEA манго-маракуйя': '#f5a300',
  'AI TEA лимон-лайм-жасмин': '#ffe01a',
  'AI TEA клубника-киви': '#d7263d',
  'AI TEA ревень': '#e0218a',
  'AI TEA персик-жасмин': '#ffb3a7',
  'Буратино классический': '#1565c0',
  'Буратино дыня-мята': '#00acc1',
  'Буратино гранат': '#7b1f3a',
  'Chino Bellini': '#c8960c',
  'Chino Rossini': '#3949ab',
  'Chino Tintoretto': '#6d4c41',
  'Chino Mimosa': '#00897b',
  'Компотай ягодный': '#ad1457',
  'Компотай гранатовый': '#8e0000',
  'Компотай сливовый': '#4a148c',
  'Компотай вишневый': '#c2185b',
  'Компотай классический': '#5c7c99',
  Tamga: '#9e9d24',
};

/** Palette for names that are not in the catalog (new SKUs): picked by a stable hash. */
export const FALLBACK_PALETTE = [
  '#e6194b',
  '#3cb44b',
  '#4363d8',
  '#f58231',
  '#911eb4',
  '#42d4f4',
  '#f032e6',
  '#bfef45',
  '#469990',
  '#9a6324',
  '#800000',
  '#000075',
] as const;

/** FNV-1a 32-bit — deterministic across sessions and browsers. */
export function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Stable colour for a subtype (canon name); null/empty -> neutral. */
export function colorForSubtype(subtype: string | null | undefined): string {
  const name = (subtype ?? '').trim();
  if (!name) return NEUTRAL_COLOR;
  const known = KNOWN_SUBTYPE_COLORS[name];
  if (known) return known;
  return FALLBACK_PALETTE[hashString(name) % FALLBACK_PALETTE.length];
}

export interface LegendEntry {
  subtype: string | null;
  color: string;
  count: number;
}

/** Legend for the photo: one entry per subtype of our (non-competitor) boxes, most frequent first. */
export function legendFor(boxes: readonly DetectedBox[]): LegendEntry[] {
  const counts = new Map<string | null, number>();
  for (const b of boxes) {
    if (isForeign(b.label)) continue;
    const key = b.subtype ? b.subtype : null;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([subtype, count]) => ({ subtype, count, color: colorForSubtype(subtype) }))
    .sort((a, b) => {
      if ((a.subtype === null) !== (b.subtype === null)) return a.subtype === null ? 1 : -1;
      return b.count - a.count || (a.subtype ?? '').localeCompare(b.subtype ?? '', 'ru');
    });
}
