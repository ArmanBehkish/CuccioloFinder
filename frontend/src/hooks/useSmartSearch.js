import { useState, useCallback } from 'react';
import { searchDogs } from '../api/dogs';

const STORAGE_KEY = 'smartSearchState';

function loadSavedState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return null;
}

function saveState(query, limit, results) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ query, limit, results }));
  } catch { /* ignore */ }
}

export function useSmartSearch() {
  const saved = loadSavedState();
  const [query, setQuery] = useState(saved?.query || '');
  const [limit, setLimit] = useState(saved?.limit || 10);
  const [results, setResults] = useState(saved?.results || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const search = useCallback(async (searchQuery, searchLimit) => {
    const trimmed = searchQuery.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      const data = await searchDogs(trimmed, searchLimit);
      setResults(data);
      saveState(trimmed, searchLimit, data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const clearSearch = useCallback(() => {
    setQuery('');
    setLimit(10);
    setResults(null);
    setError(null);
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
  }, []);

  return { query, setQuery, limit, setLimit, results, loading, error, search, clearSearch };
}
