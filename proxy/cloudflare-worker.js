/**
 * Cloudflare Worker — прокси для Claude API (Anthropic).
 *
 * Ключевое отличие от наивной реализации:
 * - Тело запроса и ответа передаётся как ReadableStream (без буферизации)
 * - Это позволяет проксировать большие payload'ы (base64-изображения для Vision)
 *   и streaming-ответы (SSE) без таймаутов
 *
 * Деплой:
 *   npx wrangler deploy
 *
 * Или через дашборд Cloudflare:
 *   Workers & Pages → Create → Paste this code → Deploy
 */

const TARGET_BASE = "https://api.anthropic.com";

// Заголовки, которые пробрасываем от клиента к Claude API
const FORWARD_REQUEST_HEADERS = [
  "x-api-key",
  "anthropic-version",
  "content-type",
  "anthropic-beta",
];

// Заголовки, которые пробрасываем от Claude API к клиенту
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "request-id",
  "x-request-id",
];

export default {
  async fetch(request) {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": FORWARD_REQUEST_HEADERS.join(", "),
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    // Формируем целевой URL (сохраняем путь и query string)
    const url = new URL(request.url);
    const targetUrl = `${TARGET_BASE}${url.pathname}${url.search}`;

    // Собираем заголовки для проксируемого запроса
    const headers = new Headers();
    for (const name of FORWARD_REQUEST_HEADERS) {
      const value = request.headers.get(name);
      if (value) {
        headers.set(name, value);
      }
    }

    // Проксируем запрос — тело передаём как stream (без буферизации!)
    // Это критично для Vision-запросов с base64-изображениями (1-5 MB)
    const response = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: request.body,  // ReadableStream — НЕ буферизуется
    });

    // Собираем заголовки ответа
    const responseHeaders = new Headers();
    responseHeaders.set("Access-Control-Allow-Origin", "*");
    for (const name of FORWARD_RESPONSE_HEADERS) {
      const value = response.headers.get(name);
      if (value) {
        responseHeaders.set(name, value);
      }
    }

    // Возвращаем ответ — тело тоже как stream (без буферизации!)
    // Это критично для SSE streaming-ответов от Claude API
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  },
};
