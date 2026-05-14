import { useState, useEffect } from 'react';
import { getDog } from '../api/dogs';

export function useDogDetail(id) {
  const [dog, setDog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getDog(id)
      .then((data) => setDog(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  return { dog, loading, error };
}
