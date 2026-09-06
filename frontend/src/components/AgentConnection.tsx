import { useState } from "react";
import { Button } from "@/components/ui/button";

export function AgentConnection({ repoId }: { repoId: string }) {
  const [client, setClient] = useState("codex");
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}/mcp/`;
  const config = client === "codex"
    ? `[mcp_servers.attocode-code-intel-remote]\nurl = "${url}"\nbearer_token_env_var = "ATTOCODE_API_KEY"\n\n[mcp_servers.attocode-code-intel-remote.http_headers]\nX-Attocode-Workspace = "${repoId}"\nX-Attocode-Profile = "daily"`
    : JSON.stringify({ mcpServers: { "attocode-code-intel-remote": {
        url, headers: { Authorization: client === "claude" ? "Bearer ${ATTOCODE_API_KEY}" : "Bearer ${env:ATTOCODE_API_KEY}", "X-Attocode-Workspace": repoId, "X-Attocode-Profile": "daily" },
      }}}, null, 2);
  return <details className="rounded-lg border border-border p-4">
    <summary className="cursor-pointer font-medium">Connect your coding agent</summary>
    <div className="mt-3 space-y-3">
      <p className="text-sm text-muted-foreground">Create an API key with intelligence:read scope in organization settings, then set ATTOCODE_API_KEY in your agent’s environment. Add intelligence:write to share project knowledge.</p>
      <label className="flex items-center gap-2 text-sm">Agent
        <select className="rounded border border-border bg-background p-2" value={client} onChange={event => {setClient(event.target.value); setCopied(false);}}>
          <option value="codex">Codex</option><option value="claude">Claude Code</option><option value="cursor">Cursor</option>
        </select>
      </label>
      <pre className="overflow-x-auto rounded bg-muted p-3 text-xs">{config}</pre>
      <Button size="sm" onClick={async () => {await navigator.clipboard.writeText(config); setCopied(true);}}>{copied ? "Copied" : "Copy configuration"}</Button>
      <p className="text-sm text-muted-foreground">This connection analyzes committed branches. Keep the local integration enabled for your working changes.</p>
    </div>
  </details>;
}
