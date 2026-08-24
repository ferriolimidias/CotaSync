import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { mockClients, type ClientRow } from "@/lib/mock-data";
import { Plus, Upload, Download, Search, ChevronDown, PowerOff } from "lucide-react";

export const Route = createFileRoute("/clientes")({
  head: () => ({ meta: [{ title: "Clientes — CotaSync" }] }),
  component: ClientesPage,
});

const columns: Column<ClientRow>[] = [
  { key: "n", header: "Nome", cell: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "l", header: "Lista/grupo", cell: (r) => r.list },
  { key: "g", header: "Grupo", cell: (r) => r.grupo },
  { key: "c", header: "Cota", cell: (r) => r.cota },
  { key: "v", header: "Versão", cell: (r) => r.versao },
  { key: "s", header: "Status", cell: (r) => (
    <BadgeStatus tone={r.active ? "success" : "neutral"}>{r.active ? "Ativo" : "Inativo"}</BadgeStatus>
  )},
  { key: "u", header: "Última consulta", cell: (r) => <span className="text-xs text-muted-foreground">{r.lastQuery}</span> },
  { key: "r", header: "Último resultado", cell: (r) => r.lastResult },
  { key: "a", header: "", cell: () => (
    <div className="flex gap-1">
      <Button size="sm" variant="ghost">Editar</Button>
      <Button size="sm" variant="ghost"><PowerOff className="h-3.5 w-3.5" /> Desativar</Button>
      <Button size="sm" variant="ghost">Histórico</Button>
    </div>
  )},
];

function NewClientDialog() {
  const [open, setOpen] = useState(false);
  const [advOpen, setAdvOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm"><Plus className="h-4 w-4" /> Novo cliente</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Novo cliente</DialogTitle></DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="c-name">Nome do cliente</Label>
            <Input id="c-name" placeholder="Ex.: Cliente Alfa" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="c-list">Lista/grupo</Label>
            <Select>
              <SelectTrigger id="c-list"><SelectValue placeholder="Selecione uma lista" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="p">Lista Principal</SelectItem>
                <SelectItem value="v">Lista VIP</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <Label htmlFor="c-active" className="text-sm">Ativo</Label>
              <p className="text-xs text-muted-foreground">Incluir nas execuções em massa e agendamentos.</p>
            </div>
            <Switch id="c-active" defaultChecked />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-2"><Label htmlFor="c-g">Grupo</Label><Input id="c-g" placeholder="935" /></div>
            <div className="grid gap-2"><Label htmlFor="c-c">Cota</Label><Input id="c-c" placeholder="110" /></div>
            <div className="grid gap-2"><Label htmlFor="c-v">Versão</Label><Input id="c-v" placeholder="00" /></div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="c-notes">Notas</Label>
            <Textarea id="c-notes" rows={2} placeholder="Observações internas (opcional)" />
          </div>

          <Collapsible open={advOpen} onOpenChange={setAdvOpen}>
            <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40">
              Avançado / outras variáveis
              <ChevronDown className={`h-4 w-4 transition ${advOpen ? "rotate-180" : ""}`} />
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <Textarea
                rows={5}
                placeholder='{ "cpf": "...", "contrato": "..." }'
                className="font-mono text-xs"
              />
              <p className="mt-1 text-xs text-muted-foreground">JSON opcional para variáveis extras usadas em ações específicas.</p>
            </CollapsibleContent>
          </Collapsible>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancelar</Button>
          <Button onClick={() => setOpen(false)}>Salvar cliente</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ClientesPage() {
  return (
    <AppShell title="Clientes" subtitle="Base fixa reutilizada em ações e agendamentos">
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input placeholder="Buscar por nome" className="pl-8" />
          </div>
          <Select>
            <SelectTrigger className="w-40"><SelectValue placeholder="Lista/grupo" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as listas</SelectItem>
              <SelectItem value="p">Lista Principal</SelectItem>
              <SelectItem value="v">Lista VIP</SelectItem>
            </SelectContent>
          </Select>
          <Select>
            <SelectTrigger className="w-32"><SelectValue placeholder="Status" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="a">Ativos</SelectItem>
              <SelectItem value="i">Inativos</SelectItem>
            </SelectContent>
          </Select>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm"><Download className="h-4 w-4" /> Modelo CSV</Button>
            <Button variant="outline" size="sm"><Upload className="h-4 w-4" /> Importar CSV</Button>
            <NewClientDialog />
          </div>
        </CardContent>
      </Card>

      <DataTable columns={columns} data={mockClients} />
    </AppShell>
  );
}
