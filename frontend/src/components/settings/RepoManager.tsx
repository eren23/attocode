import { useState } from "react";
import {
  useOrgRepos,
  useCreateRepo,
  useDeleteRepo,
  useRepoCredentialStatus,
  useSetRepoCredential,
  useDeleteRepoCredential,
  useReindexRepo,
} from "@/api/hooks/useOrgs";
import type { RepoResponse } from "@/api/generated/schema";
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
import { Plus, Trash2, KeyRound, RefreshCw } from "lucide-react";

const CRED_TYPES = [
  { value: "pat", label: "PAT" },
  { value: "deploy_token", label: "Deploy Token" },
  { value: "ssh_key", label: "SSH Key" },
] as const;

function CredentialBadge({ orgId, repo }: { orgId: string; repo: RepoResponse }) {
  const { data } = useRepoCredentialStatus(orgId, repo.id);
  if (!data) return <Badge variant="outline">Loading...</Badge>;
  if (!data.configured) return <Badge variant="warning">No credential</Badge>;
  const label = CRED_TYPES.find((t) => t.value === data.cred_type)?.label ?? data.cred_type;
  return <Badge variant="success">{label} configured</Badge>;
}

export function RepoManager({ orgId }: { orgId: string }) {
  const repos = useOrgRepos(orgId);
  const createRepo = useCreateRepo();
  const deleteRepo = useDeleteRepo();
  const setCred = useSetRepoCredential();
  const deleteCred = useDeleteRepoCredential();
  const reindex = useReindexRepo();

  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCloneUrl, setNewCloneUrl] = useState("");
  const [newBranch, setNewBranch] = useState("");

  const [credRepoId, setCredRepoId] = useState<string | null>(null);
  const [credType, setCredType] = useState("pat");
  const [credValue, setCredValue] = useState("");

  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const handleAdd = () => {
    if (!newName.trim()) return;
    createRepo.mutate(
      {
        orgId,
        name: newName.trim(),
        clone_url: newCloneUrl.trim() || undefined,
        default_branch: newBranch.trim() || undefined,
      },
      {
        onSuccess: () => {
          setNewName("");
          setNewCloneUrl("");
          setNewBranch("");
          setShowAdd(false);
        },
      },
    );
  };

  const handleSetCredential = (repoId: string) => {
    if (!credValue.trim()) return;
    setCred.mutate(
      { orgId, repoId, cred_type: credType, value: credValue },
      {
        onSuccess: () => {
          setCredRepoId(null);
          setCredValue("");
        },
      },
    );
  };

  const handleDeleteRepo = (repoId: string) => {
    deleteRepo.mutate(
      { orgId, repoId },
      { onSuccess: () => setConfirmDelete(null) },
    );
  };

  if (repos.isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowAdd(!showAdd)}
        >
          <Plus className="h-3 w-3" />
          Add Repository
        </Button>
      </div>

      {showAdd && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <div className="flex items-center gap-2">
            <Input
              placeholder="Repository name *"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="flex-1"
            />
            <Input
              placeholder="Clone URL (optional)"
              value={newCloneUrl}
              onChange={(e) => setNewCloneUrl(e.target.value)}
              className="flex-1"
            />
            <Input
              placeholder="Branch (default: main)"
              value={newBranch}
              onChange={(e) => setNewBranch(e.target.value)}
              className="w-40"
            />
          </div>
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={createRepo.isPending || !newName.trim()}
            >
              Add
            </Button>
          </div>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Clone URL</TableHead>
            <TableHead>Branch</TableHead>
            <TableHead>Index Status</TableHead>
            <TableHead>Credential</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {repos.data?.repositories?.map((repo) => (
            <TableRow key={repo.id}>
              <TableCell className="font-medium">{repo.name}</TableCell>
              <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                {repo.clone_url || "-"}
              </TableCell>
              <TableCell>
                <Badge variant="outline">{repo.default_branch}</Badge>
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    repo.index_status === "ready"
                      ? "success"
                      : repo.index_status === "indexing"
                        ? "default"
                        : "secondary"
                  }
                >
                  {repo.index_status}
                </Badge>
                {repo.last_indexed_at && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    {formatRelativeTime(repo.last_indexed_at)}
                  </span>
                )}
              </TableCell>
              <TableCell>
                <CredentialBadge orgId={orgId} repo={repo} />
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    title="Set credential"
                    onClick={() =>
                      setCredRepoId(credRepoId === repo.id ? null : repo.id)
                    }
                  >
                    <KeyRound className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    title="Reindex"
                    onClick={() => reindex.mutate({ orgId, repoId: repo.id })}
                    disabled={reindex.isPending}
                  >
                    <RefreshCw className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    title="Delete repository"
                    onClick={() => setConfirmDelete(repo.id)}
                  >
                    <Trash2 className="h-3 w-3 text-destructive" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Credential inline form */}
      {credRepoId && (
        <div className="rounded-md border border-border p-3 space-y-2">
          <p className="text-sm font-medium">
            Set credential for{" "}
            {repos.data?.repositories?.find((r) => r.id === credRepoId)?.name}
          </p>
          <div className="flex items-center gap-2">
            <select
              value={credType}
              onChange={(e) => setCredType(e.target.value)}
              className="rounded-md border border-border bg-transparent px-3 py-2 text-sm"
            >
              {CRED_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <Input
              type="password"
              placeholder="Token or key value"
              value={credValue}
              onChange={(e) => setCredValue(e.target.value)}
              className="flex-1"
            />
            <Button
              size="sm"
              onClick={() => handleSetCredential(credRepoId)}
              disabled={setCred.isPending || !credValue.trim()}
            >
              Save
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                deleteCred.mutate({ orgId, repoId: credRepoId })
              }
              disabled={deleteCred.isPending}
            >
              Remove
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setCredRepoId(null);
                setCredValue("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 flex items-center justify-between">
          <p className="text-sm">
            Delete{" "}
            <strong>
              {repos.data?.repositories?.find((r) => r.id === confirmDelete)?.name}
            </strong>
            ? This cannot be undone.
          </p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              size="sm"
              onClick={() => handleDeleteRepo(confirmDelete)}
              disabled={deleteRepo.isPending}
            >
              Delete
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmDelete(null)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
