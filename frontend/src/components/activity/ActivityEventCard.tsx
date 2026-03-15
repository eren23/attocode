import type { ActivityEvent } from "@/api/generated/schema";
import { formatRelativeTime } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import {
  Building2,
  UserPlus,
  UserMinus,
  GitBranch,
  Shield,
  Activity,
} from "lucide-react";

const EVENT_ICONS: Record<string, typeof Activity> = {
  "org.created": Building2,
  "member.invited": UserPlus,
  "member.removed": UserMinus,
  "member.role_changed": Shield,
  "repo.created": GitBranch,
};

export function ActivityEventCard({ event }: { event: ActivityEvent }) {
  const Icon = EVENT_ICONS[event.event_type] ?? Activity;

  return (
    <div className="flex items-start gap-3 rounded-md border border-border bg-card px-4 py-3">
      <div className="mt-0.5 rounded-md bg-primary/10 p-1.5">
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">
            {event.event_type}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {formatRelativeTime(event.created_at)}
          </span>
        </div>
        {Object.keys(event.detail).length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground truncate">
            {JSON.stringify(event.detail)}
          </p>
        )}
      </div>
    </div>
  );
}
