/** Server-Sent Events consumer.
 *
 *  Yields parsed events from an SSE response (`data: <json>\n\n` per record). Aborts
 *  cleanly when the AbortSignal fires. Used by the automation run event stream.
 */

export async function* parseSSE<T = unknown>(
  res: Response,
  signal?: AbortSignal
): AsyncIterableIterator<T> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (!payload || payload === '[DONE]') continue;
        try {
          yield JSON.parse(payload) as T;
        } catch {
          // malformed event — skip and keep going
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
}
