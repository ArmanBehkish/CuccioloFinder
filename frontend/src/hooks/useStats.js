import { useState, useEffect } from 'react';
import { getStats } from '../api/dogs';

// Module-level cache: /api/stats is small (~10-15 KB for ~124 dogs) and
// already cached server-side. Fetching once per session and aggregating
// client-side lets tab switches be instant.
let cachedStats = null;

export function useStats(enabled = true) {
  const [stats, setStats] = useState(cachedStats);
  const [loading, setLoading] = useState(!cachedStats && enabled);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!enabled || cachedStats) return;

    setLoading(true);
    getStats()
      .then((data) => {
        cachedStats = data;
        setStats(data);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [enabled]);

  return { stats, loading, error };
}
