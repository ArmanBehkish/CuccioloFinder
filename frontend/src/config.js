const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const IMAGE_PREFIX = import.meta.env.VITE_IMAGE_PREFIX || '';

/**
 * Resolve an image URL from the API to a full URL.
 * - null → null (caller should use placeholder)
 * - "/images/file.jpg" → IMAGE_PREFIX + "/images/file.jpg"
 * - "https://..." → returned as-is
 */
export function resolveImageUrl(path) {
  if (!path) return null;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return `${IMAGE_PREFIX}${path}`;
}

export { API_BASE_URL, IMAGE_PREFIX };
