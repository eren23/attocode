import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ApiKeyResponse, ApiKeyCreateResponse } from "@/api/generated/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { formatRelativeTime } from "@/lib/format";
import { Plus, Trash2, Copy, Check } from "lucide-react";

export function ApiKeyManager({ orgId }: { orgId: string }) {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const keys = useQuery({
    queryKey: ["api-keys", orgId],
    queryFn: () =>
      apiFetch<{ keys: ApiKeyResponse[] }>(`/api/v1/orgs/${orgId}/api-keys`),
  });

  const create = useMutation({
    mutationFn: (keyName: string) =>
      apiFetch<ApiKeyCreateResponse>(`/api/v1/orgs/${orgId}/api-keys`, {
        method: "POST",
        body: JSON.stringify({ name: keyName }),
      }),
    onSuccess: (data) => {
      setNewKey(data.key);
      setName("");
      qc.invalidateQueries({ queryKey: ["api-keys", orgId] });
    },
  });

  const revoke = useMutation({
    mutationFn: (keyId: string) =>
      apiFetch<{ detail: string }>(
        `/api/v1/orgs/${orgId}/api-keys/${keyId}`,
        { method: "DELETE" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys", orgId] }),
  });

  const handleCopy = async () => {
    if (newKey) {
      await navigator.clipboard.writeText(newKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (keys.isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowCreate(!showCreate)}
        >
          <Plus className="h-3 w-3" />
          Create Key
        </Button>
      </div>

      {showCreate && (
        <div className="flex items-center gap-2 rounded-md border border-border p-3">
          <Input
            placeholder="Key name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="flex-1"
          />
          <Button
            size="sm"
            onClick={() => name && create.mutate(name)}
            disabled={create.isPending}
          >
            Create
          </Button>
        </div>
      )}

      {newKey && (
        <div className="rounded-md border border-primary/30 bg-primary/5 p-3">
          <p className="text-sm font-medium mb-2">
            Copy your API key now — it won't be shown again
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs font-mono text-primary truncate">
              {newKey}
            </code>
            <Button variant="outline" size="icon" onClick={handleCopy}>
              {copied ? (
                <Check className="h-3 w-3 text-success" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
            </Button>
          </div>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Prefix</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Last Used</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.data?.keys?.map((k) => (
            <TableRow key={k.id}>
              <TableCell className="font-medium">{k.name}</TableCell>
              <TableCell>
                <Badge variant="outline" className="font-mono">
                  {k.key_prefix}...
                </Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatRelativeTime(k.created_at)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {k.last_used_at
                  ? formatRelativeTime(k.last_used_at)
                  : "Never"}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => revoke.mutate(k.id)}
                >
                  <Trash2 className="h-3 w-3 text-destructive" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
