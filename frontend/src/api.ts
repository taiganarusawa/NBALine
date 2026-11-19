// Every call to the server (webapp.py) goes through here. Errors come back as { error: "..." }
// and are thrown as normal errors, so callers can just show error.message.

interface Options {
  method?: string;
  body?: unknown;
  /** Give up (throw) when the server hasn't answered by then. A request from a phone that slept or lost
   *  its connection can otherwise wait forever, and a page that checks again only after an answer stops. */
  timeoutMs?: number;
}

export async function api<T>(path: string, { method = "GET", body, timeoutMs }: Options = {}): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: timeoutMs ? AbortSignal.timeout(timeoutMs) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data as T;
}

export const post = <T>(path: string, body: unknown, options: Omit<Options, "method" | "body"> = {}) =>
  api<T>(path, { ...options, method: "POST", body });

/** An error's message, whatever was thrown. */
export const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));
