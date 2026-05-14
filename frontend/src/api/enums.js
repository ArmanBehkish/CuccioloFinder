import { apiGet, apiPost } from './client';

export async function fetchEnums() {
  return apiGet('/api/enums');
}

export async function refreshStatsCache() {
  // Refreshes API-side enum/stat caches after data changes.
  return apiPost('/api/stats/refresh');
}
