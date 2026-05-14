import { useState, useCallback } from 'react';
import { filterDogs } from '../api/dogs';

const PAGE_SIZE = 20;
const STORAGE_KEY = 'filterSearchState';

const INITIAL_FILTERS = {
  source_site: '',
  gender: '',
  size: '',
  // Claimed breed — shelter's structured breed OR LLM-extracted from description.
  // Sent to the API as `breed` (substring match across breed_en + breed_from_desc).
  breed_claimed: '',
  // Detected breed — exact AKC name from the AI inference rows.
  // Sent to the API as `breed_detected`.
  breed_detected: '',
  age: '',
  fur: '',
  weight: '',
  good_with: '',
  bad_with: '',
  microchip: '',
  sterilization: '',
  vaccine: '',
  deworming: '',
  posted_interval: '',
  shelter_interval: '',
};

function loadSavedState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return null;
}

function saveState(filters, page, results) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ filters, page, results }));
  } catch { /* ignore */ }
}

export const TIME_INTERVALS = [
  { value: '1w', label: 'Last week' },
  { value: '2w', label: 'Last 2 weeks' },
  { value: '1m', label: 'Last month' },
  { value: '2m', label: 'Last 2 months' },
  { value: '3m', label: 'Last 3 months' },
  { value: '1y', label: 'Last year' },
  { value: '2y', label: 'Last 2 years' },
  { value: '2y+', label: 'More than 2 years' },
];

function daysAgo(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().split('T')[0];
}

function intervalToDateParams(interval, fromKey, toKey) {
  if (!interval) return {};
  switch (interval) {
    case '1w': return { [fromKey]: daysAgo(7) };
    case '2w': return { [fromKey]: daysAgo(14) };
    case '1m': return { [fromKey]: daysAgo(30) };
    case '2m': return { [fromKey]: daysAgo(60) };
    case '3m': return { [fromKey]: daysAgo(90) };
    case '1y': return { [fromKey]: daysAgo(365) };
    case '2y': return { [fromKey]: daysAgo(730) };
    case '2y+': return { [toKey]: daysAgo(730) };
    default: return {};
  }
}

export function useFilterSearch() {
  const saved = loadSavedState();
  const [filters, setFilters] = useState(saved?.filters || INITIAL_FILTERS);
  const [page, setPage] = useState(saved?.page || 1);
  const [results, setResults] = useState(saved?.results || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const search = useCallback(async (searchFilters, searchPage = 1) => {
    setLoading(true);
    setError(null);
    try {
      const {
        posted_interval,
        shelter_interval,
        breed_claimed,
        ...apiFilters
      } = searchFilters;
      const dateParams = {
        ...intervalToDateParams(posted_interval, 'post_date_from', 'post_date_to'),
        ...intervalToDateParams(shelter_interval, 'shelter_since_from', 'shelter_since_to'),
      };
      const data = await filterDogs({
        ...apiFilters,
        breed: breed_claimed,
        ...dateParams,
        page: searchPage,
        page_size: PAGE_SIZE,
      });
      setResults(data);
      setPage(searchPage);
      saveState(searchFilters, searchPage, data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const updateFilter = useCallback((key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(INITIAL_FILTERS);
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
  }, []);

  const totalPages = results ? Math.ceil(results.total / PAGE_SIZE) : 0;

  return {
    filters,
    updateFilter,
    resetFilters,
    page,
    totalPages,
    results,
    loading,
    error,
    search,
  };
}
