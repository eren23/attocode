import { useParams } from "react-router";
import { useOrgActivity } from "@/api/hooks/useActivity";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { Activity } from "lucide-react";

export function ActivityPage() {
  const { orgId } = useParams();
  const { data, isLoading } = useOrgActivity(orgId!);

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-xl font-bold">Activity</h1>
      {data?.events.length ? (
        <ActivityFeed events={data.events} />
      ) : (
        <EmptyState
          icon={<Activity className="h-12 w-12" />}
          title="No activity yet"
          description="Actions in your organization will appear here"
        />
      )}
    </div>
  );
}
