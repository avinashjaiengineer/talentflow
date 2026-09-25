import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import EventList from "../components/EventList";
import { Card, PageHeader } from "../components/ui";

export default function ActivityPage() {
  const { data: events = [] } = useQuery({
    queryKey: ["events", "all"],
    queryFn: () => api.events({ limit: 200 }),
    refetchInterval: 3_000,
  });
  return (
    <>
      <PageHeader title="Agent activity" subtitle="The shared event log: every agent action and human decision, newest first" />
      <Card className="p-5">
        <EventList events={events} />
      </Card>
    </>
  );
}
