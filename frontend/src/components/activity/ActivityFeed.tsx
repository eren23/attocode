import type { ActivityEvent } from "@/api/generated/schema";
import { ActivityEventCard } from "./ActivityEventCard";

export function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  return (
    <div className="space-y-2">
      {events.map((event) => (
        <ActivityEventCard key={event.id} event={event} />
      ))}
    </div>
  );
}
