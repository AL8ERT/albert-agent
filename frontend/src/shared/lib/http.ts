/**
 * 轻量 HTTP 封装：统一发送 JSON 请求、解析响应并提取错误信息。
 *
 * 所有请求使用同源相对路径 /api，开发环境下由 Vite dev server 代理到后端
 * （见 vite.config.ts 的 server.proxy）。
 */

/** 从非 2xx 响应中提取后端返回的 detail 字段，转成可展示的 Error。 */
async function errorFromResponse(response: Response): Promise<Error> {
  try {
    const body: unknown = await response.json()
    if (
      typeof body === 'object' &&
      body !== null &&
      'detail' in body &&
      typeof (body as { detail: unknown }).detail === 'string'
    ) {
      return new Error((body as { detail: string }).detail)
    }
  } catch {
    // 响应不是 JSON 时退化为通用错误
    return new Error(`Request failed with status ${response.status}`)
  }
  return new Error(`Request failed with status ${response.status}`)
}

/** 发送 POST JSON 请求；HTTP 状态非 2xx 时抛出 Error。 */
export async function postJson(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    throw await errorFromResponse(response)
  }
  return response
}

/** 发送 GET 请求并解析 JSON 响应。 */
export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, { signal })

  if (!response.ok) {
    throw await errorFromResponse(response)
  }
  return (await response.json()) as T
}
