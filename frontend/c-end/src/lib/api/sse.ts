/**
 * SSE 流式请求封装（fetch + ReadableStream）。
 *
 * 后端事件类型（API §2）：intent / thinking / tool_call / tool_result / token /
 * plan_card / interaction / citation / error / done / ping。
 * 心跳 15s；服务端中断（interrupt）不关闭连接。
 */

export type SSEEventType =
  | 'intent'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'token'
  | 'plan_card'
  | 'interaction'
  | 'citation'
  | 'error'
  | 'done'
  | 'ping';

export interface SSEEvent<T = unknown> {
  type: SSEEventType;
  data: T;
}

export interface SSEOptions {
  url: string;
  body: unknown;
  accessToken: string | null;
  signal?: AbortSignal;
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
}

/** 解析 `data: xxx\n\n` 分帧，返回每帧的 JSON */
function parseChunk(buffer: string): { events: SSEEvent[]; rest: string } {
  const events: SSEEvent[] = [];
  const frames = buffer.split('\n\n');
  const rest = frames.pop() ?? '';

  for (const frame of frames) {
    const dataLines = frame
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());

    if (dataLines.length === 0) continue;

    try {
      events.push(JSON.parse(dataLines.join('\n')) as SSEEvent);
    } catch {
      // 单帧解析失败不应中断整个流
      console.warn('[sse] 无法解析的事件帧', frame);
    }
  }

  return { events, rest };
}

export async function createSSEConnection(options: SSEOptions): Promise<void> {
  const { url, body, accessToken, signal, onEvent, onError, onClose } = options;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
      credentials: 'include',
    });

    if (!response.ok || !response.body) {
      throw new Error(`SSE 连接失败: HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseChunk(buffer);
      buffer = rest;

      for (const event of events) {
        onEvent(event);
        if (event.type === 'done' || event.type === 'error') {
          onClose?.();
          return;
        }
      }
    }

    onClose?.();
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      onClose?.();
      return;
    }
    onError?.(error instanceof Error ? error : new Error(String(error)));
  }
}
