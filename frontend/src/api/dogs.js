import { apiGet, apiPost } from './client';

export async function filterDogs(filters) {
  return apiGet('/api/filter-dogs', filters);
}

export async function getDog(id) {
  return apiGet(`/api/dogs/${id}`);
}

export async function searchDogs(query, limit = 10) {
  return apiPost('/api/dogs/search', { query, limit });
}

export async function getWorkerStatus() {
  return apiGet('/api/worker/status');
}

export async function getStats() {
  return apiGet('/api/stats');
}
