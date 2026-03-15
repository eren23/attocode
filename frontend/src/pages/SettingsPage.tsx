import { useState } from "react";
import { useParams } from "react-router";
import { useOrg, useOrgMembers } from "@/api/hooks/useOrgs";
import { MemberList } from "@/components/settings/MemberList";
import { ApiKeyManager } from "@/components/settings/ApiKeyManager";
import { RepoManager } from "@/components/settings/RepoManager";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { TabGroup } from "@/components/ui/tabs";

const TABS = ["Members", "API Keys", "Repositories"] as const;

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

      <TabGroup items={TABS} value={tab} onChange={setTab} />

      {tab === "Members" && (
        <MemberList
          orgId={orgId!}
          members={members.data?.members ?? []}
          loading={members.isLoading}
        />
      )}

      {tab === "API Keys" && <ApiKeyManager orgId={orgId!} />}

      {tab === "Repositories" && <RepoManager orgId={orgId!} />}
    </div>
  );
}
