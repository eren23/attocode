import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RepoWebSocket } from "@/lib/ws";

export function useRepoWebSocket(repoId: string | undefined) {
  const qc = useQueryClient();
  const wsRef = useRef<RepoWebSocket | null>(null);

  useEffect(() => {
    if (!repoId) return;

    const ws = new RepoWebSocket(repoId);
    wsRef.current = ws;

    // Invalidate relevant queries on WS events
    ws.on("index.completed", () => {
      qc.invalidateQueries({ queryKey: ["files"] });
      qc.invalidateQueries({ queryKey: ["analysis"] });
      qc.invalidateQueries({ queryKey: ["embeddings"] });
    });
    ws.on("presence.joined", () => {
      qc.invalidateQueries({ queryKey: ["presence", repoId] });
    });
    ws.on("presence.left", () => {
      qc.invalidateQueries({ queryKey: ["presence", repoId] });
    });
    ws.on("activity.new", () => {
      qc.invalidateQueries({ queryKey: ["activity"] });
    });

    ws.connect();

    return () => {
      ws.disconnect();
      wsRef.current = null;
    };
  }, [repoId, qc]);

  return wsRef;
}
