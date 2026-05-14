// Pure aggregation helpers over the `/api/stats` `dogs` array.
// All helpers exclude nulls/empties from denominators unless documented.

// ===== _en / _from_desc resolution =====

// Sentinel-aware truthy check shared with the DogDetailPage display rule:
//   - null / undefined → falsy
//   - '' → falsy (LLM "no signal" sentinel on scalar columns)
//   - [] → falsy (same sentinel on array columns)
//   - anything else → truthy
function isTruthy(v) {
  if (v === null || v === undefined) return false;
  if (typeof v === 'string' && v === '') return false;
  if (Array.isArray(v) && v.length === 0) return false;
  return true;
}

// resolve(row, 'size') -> row.size_en if populated, else row.size_from_desc.
// Mirrors the DogDetailPage display rule. For raw IT-only fields like
// `weight`, callers pass `weight` and we treat the bare column as `_en`.
export function resolve(row, baseKey) {
  const enKey = row[`${baseKey}_en`] !== undefined ? `${baseKey}_en` : baseKey;
  const en = row[enKey];
  if (isTruthy(en)) return en;
  return row[`${baseKey}_from_desc`];
}

// ===== Generic counters =====

// countBy(rows, 'gender_en') -> [{ name: 'male', value: 42 }, ...]
// Skips null/undefined/'' values from the buckets. Pass includeUnknown=true
// to add an "Unknown" slice for those skipped rows (used for donuts so the
// pie always sums to 100% of dogs).
export function countBy(rows, key, { includeUnknown = false, unknownLabel = 'Unknown' } = {}) {
  const counts = {};
  let unknown = 0;
  for (const r of rows) {
    const v = r[key];
    if (!isTruthy(v)) {
      unknown += 1;
      continue;
    }
    counts[v] = (counts[v] || 0) + 1;
  }
  const out = Object.entries(counts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
  if (includeUnknown && unknown > 0) out.push({ name: unknownLabel, value: unknown });
  return out;
}

// Same as countBy but resolves _en / _from_desc into a single canonical value
// before bucketing. Use this for any field with a description-extracted sibling.
export function countByResolved(rows, baseKey, { includeUnknown = false, unknownLabel = 'Unknown' } = {}) {
  const counts = {};
  let unknown = 0;
  for (const r of rows) {
    const v = resolve(r, baseKey);
    if (!isTruthy(v)) {
      unknown += 1;
      continue;
    }
    counts[v] = (counts[v] || 0) + 1;
  }
  const out = Object.entries(counts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
  if (includeUnknown && unknown > 0) out.push({ name: unknownLabel, value: unknown });
  return out;
}

// Flatten JSON-array columns (good_with_en, bad_with_en).
export function countByMulti(rows, key) {
  const counts = {};
  for (const r of rows) {
    const arr = r[key];
    if (!Array.isArray(arr)) continue;
    for (const v of arr) {
      if (!v) continue;
      counts[v] = (counts[v] || 0) + 1;
    }
  }
  return Object.entries(counts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

// Same as countByMulti but uses resolve() to pick between _en / _from_desc
// array columns. Pass the base name (e.g. 'good_with').
export function countByMultiResolved(rows, baseKey) {
  const counts = {};
  for (const r of rows) {
    const arr = resolve(r, baseKey);
    if (!Array.isArray(arr)) continue;
    for (const v of arr) {
      if (!v) continue;
      counts[v] = (counts[v] || 0) + 1;
    }
  }
  return Object.entries(counts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

// crossTab(rows, 'source_site', 'size', { colResolve: true })
// -> [{ row: 'canileoasi', small: 4, medium: 12, large: 3 }, ...]
// rowResolve / colResolve treat the given key as a baseKey and use resolve()
// instead of direct column access — needed for columns with _en/_from_desc siblings.
export function crossTab(rows, rowKey, colKey, { rowResolve = false, colResolve = false } = {}) {
  const acc = {};
  const allCols = new Set();
  for (const r of rows) {
    const rv = rowResolve ? resolve(r, rowKey) : r[rowKey];
    const cv = colResolve ? resolve(r, colKey) : r[colKey];
    if (!isTruthy(rv)) continue;
    if (!isTruthy(cv)) continue;
    if (!acc[rv]) acc[rv] = {};
    acc[rv][cv] = (acc[rv][cv] || 0) + 1;
    allCols.add(cv);
  }
  const result = Object.entries(acc).map(([rv, cols]) => {
    const obj = { row: rv };
    for (const c of allCols) obj[c] = cols[c] || 0;
    return obj;
  });
  return { data: result.sort((a, b) => a.row.localeCompare(b.row)), keys: [...allCols].sort() };
}

// ===== Medical compliance =====

// Returns { yes, no, unknown, rate } where rate = yes / (yes + no).
// Treats anything outside yes/no as "unknown". `baseField` is the bare name
// ('microchip', 'vaccine', …) so we can resolve _en / _from_desc internally.
export function medicalSplit(rows, baseField) {
  let yes = 0;
  let no = 0;
  let unknown = 0;
  for (const r of rows) {
    const v = resolve(r, baseField);
    if (v === 'yes') yes += 1;
    else if (v === 'no') no += 1;
    else unknown += 1;
  }
  const known = yes + no;
  return { yes, no, unknown, rate: known === 0 ? null : yes / known };
}

// Returns [{ shelter, yes, no, unknown, rate }] for medical small-multiples.
export function medicalByShelter(rows, baseField) {
  const byShelter = {};
  for (const r of rows) {
    const s = r.source_site;
    if (!s) continue;
    if (!byShelter[s]) byShelter[s] = [];
    byShelter[s].push(r);
  }
  return Object.entries(byShelter)
    .map(([shelter, sub]) => ({ shelter, ...medicalSplit(sub, baseField) }))
    .sort((a, b) => a.shelter.localeCompare(b.shelter));
}

// ===== Completeness =====

// fieldCompleteness(rows, [{ key: 'gender', label: 'Gender', resolved: true }, ...])
//   -> [{ key, label, populated, missing, pct }]
// When `resolved` is true, the key is treated as a baseKey and resolve() is
// used; a dog counts as populated if either `_en` or `_from_desc` has a value.
export function fieldCompleteness(rows, fields) {
  const total = rows.length;
  return fields.map(({ key, label, resolved = false }) => {
    let populated = 0;
    for (const r of rows) {
      const v = resolved ? resolve(r, key) : r[key];
      if (isTruthy(v)) populated += 1;
    }
    return {
      key,
      label,
      populated,
      missing: total - populated,
      pct: total === 0 ? 0 : (populated / total) * 100,
    };
  });
}

// Per-shelter × per-field completeness — returns nivo-heatmap shape.
// shelters: [shelter], fields: [{ key, label }]
//   -> { shelters, fieldLabels, matrix: [{ id: shelter, data: [{ x: label, y: pct }] }] }
export function completenessHeatmap(rows, fields) {
  const byShelter = {};
  for (const r of rows) {
    const s = r.source_site;
    if (!s) continue;
    if (!byShelter[s]) byShelter[s] = [];
    byShelter[s].push(r);
  }
  const shelters = Object.keys(byShelter).sort();
  const fieldLabels = fields.map((f) => f.label);
  const matrix = shelters.map((s) => ({
    id: s,
    data: fields.map((f) => {
      const sub = byShelter[s];
      const completeness = fieldCompleteness(sub, [f])[0];
      return { x: f.label, y: Math.round(completeness.pct) };
    }),
  }));
  return { shelters, fieldLabels, matrix };
}

// ===== Co-occurrence (good_with × bad_with) =====

// Returns nivo-heatmap shape:
//   [{ id: goodValue, data: [{ x: badValue, y: count }, ...] }, ...]
// `goodKey` / `badKey` are base names ('good_with', 'bad_with') — resolve()
// picks the populated source per dog.
export function coOccurrence(rows, goodKey, badKey, goodVals, badVals) {
  const matrix = {};
  for (const g of goodVals) {
    matrix[g] = {};
    for (const b of badVals) matrix[g][b] = 0;
  }
  for (const r of rows) {
    const goods = Array.isArray(resolve(r, goodKey)) ? resolve(r, goodKey) : [];
    const bads = Array.isArray(resolve(r, badKey)) ? resolve(r, badKey) : [];
    for (const g of goods) {
      if (!(g in matrix)) continue;
      for (const b of bads) {
        if (!(b in matrix[g])) continue;
        matrix[g][b] += 1;
      }
    }
  }
  return goodVals.map((g) => ({
    id: g,
    data: badVals.map((b) => ({ x: b, y: matrix[g][b] })),
  }));
}

// ===== Time series =====

// ISO week key 'YYYY-Www' for a date string.
function isoWeekKey(dateStr) {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  // Move to nearest Thursday for ISO week numbering
  const target = new Date(d.valueOf());
  const dayNr = (d.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNr + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const weekNum = 1 + Math.round(((target - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
  return `${target.getUTCFullYear()}-W${String(weekNum).padStart(2, '0')}`;
}

function monthKey(dateStr) {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

// dailyCounts(rows, 'post_date') -> [{ day: 'YYYY-MM-DD', value: count }]
// Shape matches what @nivo/calendar expects (`day` + `value`).
export function dailyCounts(rows, dateField) {
  const counts = {};
  for (const r of rows) {
    const v = r[dateField];
    if (!v) continue;
    const day = String(v).slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
    counts[day] = (counts[day] || 0) + 1;
  }
  return Object.entries(counts)
    .map(([day, value]) => ({ day, value }))
    .sort((a, b) => a.day.localeCompare(b.day));
}

// weeklyCounts(rows, 'post_date') -> [{ week, count }]
export function weeklyCounts(rows, dateField) {
  const counts = {};
  for (const r of rows) {
    const v = r[dateField];
    if (!v) continue;
    const k = isoWeekKey(v);
    if (!k) continue;
    counts[k] = (counts[k] || 0) + 1;
  }
  return Object.entries(counts)
    .map(([week, count]) => ({ week, count }))
    .sort((a, b) => a.week.localeCompare(b.week));
}

// cumulativeByMonth(rows, 'post_date') -> [{ month, cumulative }]
export function cumulativeByMonth(rows, dateField) {
  const counts = {};
  for (const r of rows) {
    const v = r[dateField];
    if (!v) continue;
    const k = monthKey(v);
    if (!k) continue;
    counts[k] = (counts[k] || 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => a[0].localeCompare(b[0]));
  let cum = 0;
  return sorted.map(([month, count]) => {
    cum += count;
    return { month, cumulative: cum };
  });
}

// ===== Wait / tenure (shelter_since) =====

const MS_PER_DAY = 86400000;

export function daysSince(dateStr, now = Date.now()) {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor((now - d.getTime()) / MS_PER_DAY));
}

// Histogram of days-since-shelter_since for currently-listed dogs.
// Buckets in days: [0-30, 31-90, 91-180, 181-365, 366-730, 730+]
export function waitHistogram(rows, dateField = 'shelter_since') {
  const buckets = [
    { name: '0-1 mo', min: 0, max: 30, count: 0 },
    { name: '1-3 mo', min: 31, max: 90, count: 0 },
    { name: '3-6 mo', min: 91, max: 180, count: 0 },
    { name: '6-12 mo', min: 181, max: 365, count: 0 },
    { name: '1-2 yr', min: 366, max: 730, count: 0 },
    { name: '2+ yr', min: 731, max: Infinity, count: 0 },
  ];
  for (const r of rows) {
    const v = r[dateField];
    if (!v) continue;
    const d = daysSince(v);
    if (d === null) continue;
    for (const b of buckets) {
      if (d >= b.min && d <= b.max) {
        b.count += 1;
        break;
      }
    }
  }
  return buckets.map(({ name, count }) => ({ name, count }));
}

function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 0 ? (s[mid - 1] + s[mid]) / 2 : s[mid];
}

// averageWaitBy(rows, 'age_category')
//   -> [{ name: 'puppy', avgDays: 42, n: 5 }, ...]
// Pass `resolved: true` to resolve _en/_from_desc internally.
export function averageWaitBy(rows, key, dateField = 'shelter_since', { resolved = false } = {}) {
  const byGroup = {};
  for (const r of rows) {
    const g = resolved ? resolve(r, key) : r[key];
    const v = r[dateField];
    if (!isTruthy(g) || !v) continue;
    const d = daysSince(v);
    if (d === null) continue;
    if (!byGroup[g]) byGroup[g] = [];
    byGroup[g].push(d);
  }
  return Object.entries(byGroup)
    .map(([name, days]) => {
      const sum = days.reduce((s, x) => s + x, 0);
      return { name, avgDays: Math.round(sum / days.length), n: days.length };
    })
    .sort((a, b) => b.avgDays - a.avgDays);
}

// ===== Description length =====

const DESC_LEN_BUCKETS = [
  { name: '0', min: 0, max: 0 },
  { name: '1-100', min: 1, max: 100 },
  { name: '101-300', min: 101, max: 300 },
  { name: '301-600', min: 301, max: 600 },
  { name: '601-1000', min: 601, max: 1000 },
  { name: '1001-2000', min: 1001, max: 2000 },
  { name: '2000+', min: 2001, max: Infinity },
];

// Bins description_en char length into recharts-friendly buckets.
export function descriptionLengthHistogram(rows) {
  const buckets = DESC_LEN_BUCKETS.map((b) => ({ ...b, count: 0 }));
  for (const r of rows) {
    const v = r.description_en || '';
    const n = v.length;
    for (const b of buckets) {
      if (n >= b.min && n <= b.max) {
        b.count += 1;
        break;
      }
    }
  }
  return buckets.map(({ name, count }) => ({ name, count }));
}

// Same buckets as the histogram above, broken down by source_site. Returns
// the shape StackedBar consumes: { data: [{ row: bucket, [shelter]: n, ... }], keys: [shelter] }.
export function descriptionLengthByShelter(rows) {
  const shelters = new Set();
  const counts = {}; // counts[bucketName][shelter] = n
  for (const r of rows) {
    const s = r.source_site;
    if (!s) continue;
    shelters.add(s);
    const v = r.description_en || '';
    const n = v.length;
    const bucket = DESC_LEN_BUCKETS.find((b) => n >= b.min && n <= b.max);
    if (!bucket) continue;
    if (!counts[bucket.name]) counts[bucket.name] = {};
    counts[bucket.name][s] = (counts[bucket.name][s] || 0) + 1;
  }
  const keys = [...shelters].sort();
  const data = DESC_LEN_BUCKETS.map((b) => {
    const row = { row: b.name };
    for (const s of keys) row[s] = counts[b.name]?.[s] || 0;
    return row;
  });
  return { data, keys };
}

// ===== Breeds =====

// Top N items from a count list, with the remainder grouped as "Other".
export function topNWithOther(counts, n) {
  if (counts.length <= n) return counts;
  const head = counts.slice(0, n);
  const tail = counts.slice(n);
  const otherTotal = tail.reduce((s, c) => s + c.value, 0);
  return [...head, { name: 'Other', value: otherTotal }];
}

// Heuristic: a breed string is "mixed" if it mentions mix/cross/breed/meticcio,
// is empty, or is the sentinel '' / 'Mixed'. Used for the pure/mixed split.
export function pureVsMixed(rows) {
  let pure = 0;
  let mixed = 0;
  let unknown = 0;
  const mixedRe = /\b(mix|mixed|cross|crossbreed|meticcio|bastard|hybrid)\b/i;
  for (const r of rows) {
    const raw = resolve(r, 'breed');
    const v = (typeof raw === 'string' ? raw : '').trim();
    if (!v) {
      unknown += 1;
      continue;
    }
    if (mixedRe.test(v)) mixed += 1;
    else pure += 1;
  }
  return [
    { name: 'Pure (claimed)', value: pure },
    { name: 'Mixed', value: mixed },
    { name: 'Unknown', value: unknown },
  ];
}

// ===== KPI helpers =====

export function uniqueCount(rows, key) {
  const s = new Set();
  for (const r of rows) {
    const v = r[key];
    if (v) s.add(v);
  }
  return s.size;
}

// Counts rows with post_date in the last N days. Excludes rows missing the field.
export function recentCount(rows, dateField, days) {
  const cutoff = Date.now() - days * MS_PER_DAY;
  let n = 0;
  for (const r of rows) {
    const v = r[dateField];
    if (!v) continue;
    const t = new Date(v).getTime();
    if (!isNaN(t) && t >= cutoff) n += 1;
  }
  return n;
}
