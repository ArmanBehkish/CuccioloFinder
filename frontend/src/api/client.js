import { API_BASE_URL } from '../config';

export async function apiGet(path, params = {}) {
  const searchParams = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      searchParams.append(key, value);
    }
  }

  const queryString = searchParams.toString();
  const url = queryString
    ? `${API_BASE_URL}${path}?${queryString}`
    : `${API_BASE_URL}${path}`;

  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `API error ${response.status}`);
  }
  return response.json();
}

export async function apiPost(path, body) {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `API error ${response.status}`);
  }
  return response.json();
}
