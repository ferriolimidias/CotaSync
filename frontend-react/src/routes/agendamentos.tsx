import { createFileRoute } from "@tanstack/react-router";
import { CalendarClock } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { Card, CardContent } from "@/components/ui/card";

export const Route = createFileRoute("/agendamentos")({
  head: () => ({ meta: [{ title: "Agendamentos — CotaSync" }] }),
  component: AgendamentosPage,
});

function AgendamentosPage() {
  return (
    <AppShell title="Agendamentos" subtitle="Funcionalidade indisponível nesta versão">
      <Card>
        <CardContent className="grid min-h-[360px] place-items-center p-8 text-center">
          <div className="max-w-md">
            <div className="mx-auto grid h-12 w-12 place-items-center rounded-md bg-muted text-muted-foreground">
              <CalendarClock className="h-6 w-6" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-foreground">
              Agendamentos estarão disponíveis em breve.
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              O scheduler legado foi removido. A tela permanece como referência de navegação, sem
              criar agendamentos falsos.
            </p>
          </div>
        </CardContent>
      </Card>
    </AppShell>
  );
}
