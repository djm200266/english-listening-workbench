/**
 * Unified API configuration.
 * ALL API requests use this base URL. Pages must never hardcode URLs.
 *
 * __API_BASE_URL__ is injected by Vite at build time:
 * - Production: '' (empty = same origin, served by FastAPI)
 * - Dev: 'http://127.0.0.1:8000' (Vite dev server proxies /api to backend)
 */
declare const __API_BASE_URL__: string;
export const API_BASE_URL: string = __API_BASE_URL__;
