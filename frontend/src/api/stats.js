import { apiGet } from './client';

export async function fetchStats() {
  return apiGet('/api/stats');
}
