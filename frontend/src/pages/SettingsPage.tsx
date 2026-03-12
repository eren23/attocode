import { useState } from "react";
import { useParams } from "react-router";
import { useOrg, useOrgMembers } from "@/api/hooks/useOrgs";
import { MemberList } from "@/components/settings/MemberList";
import { ApiKeyManager } from "@/components/settings/ApiKeyManager";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { cn } from "@/lib/cn";

const TABS = ["Members", "API Keys"] as const;

export function SettingsPage() {
  const { orgId } = useParams();
  const { data: org, isLoading } = useOrg(orgId!);
  const members = useOrgMembers(orgId!);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Members");

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-xl font-bold">{org?.name} Settings</h1>
        <p className="text-sm text-muted-foreground">
          Manage members, API keys, and organization settings
        </p>
      </div>

      <div className="flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "border-b-2 px-4 py-2 text-sm transition-colors",
              t === tab
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Members" && (
        <MemberList
          orgId={orgId!}
          members={members.data?.members ?? []}
          loading={members.isLoading}
        />
      )}

      {tab === "API Keys" && <ApiKeyManager orgId={orgId!} />}
    </div>
  );
}
