import { useState, useEffect } from 'react';
import { fetchEnums, refreshStatsCache } from '../api/enums';

let cachedEnums = null;

export function useEnums(enabled = true) {
  const [enums, setEnums] = useState(cachedEnums);
  const [loading, setLoading] = useState(!cachedEnums && enabled);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!enabled || cachedEnums) return;

    setLoading(true);
    fetchEnums()
      .then((data) => {
        cachedEnums = data;
        setEnums(data);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [enabled]);

  const refreshEnums = async () => {
    // Reset can be used to force the API to rebuild enum/stat caches.
    setLoading(true);
    setError(null);
    try {
      await refreshStatsCache();
      const data = await fetchEnums();
      cachedEnums = data;
      setEnums(data);
      return data;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  return { enums, loading, error, refreshEnums };
}
