import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/cotasync/AppShell";
import { ActionCard } from "@/components/cotasync/ActionCard";
import { Button } from "@/components/ui/button";
import { mockActions } from "@/lib/mock-data";
import { Plus } from "lucide-react";

export const Route = createFileRoute("/acoes")({
  head: () => ({ meta: [{ title: "Ações — CotaSync" }] }),
  component: AcoesPage,
});

function AcoesPage() {
  return (
    <AppShell
      title="Ações"
      subtitle="Ações ensinadas e prontas para execução"
      actions={<Button size="sm"><Plus className="h-4 w-4" /> Nova ação</Button>}
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {mockActions.map((a) => <ActionCard key={a.id} action={a} />)}
      </div>
    </AppShell>
  );
}
