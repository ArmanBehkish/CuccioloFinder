// Sandy-amber palette aligned with App.css. Used cyclically for series.
export const PALETTE = [
  '#b8864e', // accent
  '#f09848', // warm orange
  '#6b5840', // dark brown (tooltip bg)
  '#a47148', // tan
  '#e9a8a8', // soft red (used in compat bad-with)
  '#4f8f78', // green from-desc marker
  '#7fa1c4', // muted blue
  '#c8a25a', // gold
  '#d97a5a', // burnt orange
  '#8a6f5a', // taupe
];

export function colorFor(i) {
  return PALETTE[i % PALETTE.length];
}

// Two-tone for yes/no medical splits (yes = warm green, no = muted red),
// with a neutral "unknown" slot.
export const MEDICAL_COLORS = {
  yes: '#4f8f78',
  no: '#d97a5a',
  unknown: '#cdbfae',
};

// Qualitative autumn palette for stacked-composition charts (size / gender /
// age × shelter). Each hue is its own family so adjacent segments stay
// distinguishable even when one is a thin slice.
export const COMPOSITION_PALETTE = [
  '#c9a66b', // golden tan
  '#e07a5f', // terracotta
  '#6b4226', // walnut
  '#81a263', // sage olive
  '#c98a7d', // dusty rose
  '#4a6072', // slate blue
  '#b8864e', // accent (fallback for >6 categories)
  '#3c2a21', // near-black (fallback)
];
