import { useState } from "react";
import type { MemberResponse } from "@/api/generated/schema";
import { useInviteMember, useRemoveMember } from "@/api/hooks/useOrgs";
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
import { UserPlus, Trash2 } from "lucide-react";

interface MemberListProps {
  orgId: string;
  members: MemberResponse[];
  loading: boolean;
}

export function MemberList({ orgId, members, loading }: MemberListProps) {
  const [showInvite, setShowInvite] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const invite = useInviteMember();
  const remove = useRemoveMember();

  const handleInvite = () => {
    if (!email.trim()) return;
    invite.mutate(
      { orgId, email, role },
      {
        onSuccess: () => {
          setEmail("");
          setShowInvite(false);
        },
      },
    );
  };

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setShowInvite(!showInvite)}>
          <UserPlus className="h-3 w-3" />
          Invite Member
        </Button>
      </div>

      {showInvite && (
        <div className="flex items-center gap-2 rounded-md border border-border p-3">
          <Input
            placeholder="Email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="flex-1"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="rounded-md border border-border bg-transparent px-3 py-2 text-sm"
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
          <Button size="sm" onClick={handleInvite} disabled={invite.isPending}>
            Invite
          </Button>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((m) => (
            <TableRow key={m.user_id}>
              <TableCell className="font-medium">{m.name}</TableCell>
              <TableCell className="text-muted-foreground">{m.email}</TableCell>
              <TableCell>
                <Badge variant="outline">{m.role}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant={m.accepted ? "success" : "warning"}>
                  {m.accepted ? "active" : "pending"}
                </Badge>
              </TableCell>
              <TableCell>
                {m.role !== "owner" && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() =>
                      remove.mutate({ orgId, userId: m.user_id })
                    }
                  >
                    <Trash2 className="h-3 w-3 text-destructive" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
