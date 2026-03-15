import { getAccessToken } from "./auth";

type EventHandler = (data: unknown) => void;

export class RepoWebSocket {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<EventHandler>>();
  private reconnectDelay = 1000;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private closed = false;
  private lastStreamId = "$";

  constructor(
    private repoId: string,
    private baseUrl = "",
  ) {}

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const token = getAccessToken();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = this.baseUrl || window.location.host;
    const url = `${protocol}//${host}/ws/repos/${this.repoId}/events?token=${token}&last_event_id=${this.lastStreamId}`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.startHeartbeat();
    };

    this.ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string) as {
          type: string;
          data: unknown;
          _stream_id?: string;
        };
        // Track stream position for replay on reconnect
        if (msg._stream_id) {
          this.lastStreamId = msg._stream_id;
        }
        const handlers = this.handlers.get(msg.type);
        if (handlers) {
          handlers.forEach((h) => h(msg.data));
        }
        // Also emit wildcard
        const all = this.handlers.get("*");
        if (all) {
          all.forEach((h) => h(msg));
        }
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();
      if (!this.closed) {
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  on(event: string, handler: EventHandler) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);
    return () => this.handlers.get(event)?.delete(handler);
  }

  send(type: string, data: unknown = {}) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    }
  }

  disconnect() {
    this.closed = true;
    this.stopHeartbeat();
    this.ws?.close();
    this.ws = null;
    this.handlers.clear();
  }

  private startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      this.send("heartbeat");
    }, 30000);
  }

  private stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
}
