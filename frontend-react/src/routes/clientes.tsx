import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, Pencil, Plus, PowerOff, Search, Upload } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { createClient, deactivateClient, getClients, updateClient } from "@/services/api";
import type { ApiClient } from "@/types/api";

export const Route = createFileRoute("/clientes")({
  head: () => ({ meta: [{ title: "Clientes — CotaSync" }] }),
  component: ClientesPage,
});

type FormState = {
  id?: string;
  name: string;
  group: string;
  active: boolean;
  grupo: string;
  cota: string;
  versao: string;
  notes: string;
};

const emptyForm: FormState = {
  name: "",
  group: "Lista Principal",
  active: true,
  grupo: "",
  cota: "",
  versao: "",
  notes: "",
};

function ClientesPage() {
  const queryClient = useQueryClient();
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => getClients({ pageSize: 200 }) });
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [status, setStatus] = useState("all");
  const [form, setForm] = useState<FormState | null>(null);

  const groups = useMemo(
    () =>
      Array.from(
        new Set((clients.data?.items ?? []).map((client) => client.group).filter(Boolean)),
      ).sort(),
    [clients.data],
  );
  const filtered = useMemo(() => {
    return (clients.data?.items ?? []).filter((client) => {
      const matchesText = client.name.toLowerCase().includes(query.toLowerCase());
      const matchesGroup = group === "all" || client.group === group;
      const matchesStatus =
        status === "all" || (status === "active" ? client.active : !client.active);
      return matchesText && matchesGroup && matchesStatus;
    });
  }, [clients.data, group, query, status]);

  const save = useMutation({
    mutationFn: async (input: FormState) => {
      const payload = {
        name: input.name,
        group: input.group,
        active: input.active,
        notes: input.notes,
        variables: { grupo: input.grupo, cota: input.cota, versao: input.versao },
      };
      return input.id ? updateClient(input.id, payload) : createClient(payload);
    },
    onSuccess: () => {
      toast.success("Cliente salvo.");
      setForm(null);
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível salvar o cliente."),
  });

  const deactivate = useMutation({
    mutationFn: deactivateClient,
    onSuccess: () => {
      toast.success("Cliente desativado.");
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível desativar o cliente."),
  });

  const columns: Column<ApiClient>[] = [
    {
      key: "n",
      header: "Nome",
      cell: (client) => <span className="font-medium text-foreground">{client.name}</span>,
    },
    { key: "l", header: "Lista/grupo", cell: (client) => client.group },
    { key: "g", header: "Grupo", cell: (client) => client.display_variables?.grupo || "-" },
    { key: "c", header: "Cota", cell: (client) => client.display_variables?.cota || "-" },
    { key: "v", header: "Versão", cell: (client) => client.display_variables?.versao || "-" },
    {
      key: "s",
      header: "Status",
      cell: (client) => (
        <BadgeStatus tone={client.active ? "success" : "neutral"}>
          {client.active ? "Ativo" : "Inativo"}
        </BadgeStatus>
      ),
    },
    {
      key: "o",
      header: "Observações",
      cell: (client) => (
        <span className="text-xs text-muted-foreground">{client.notes || "-"}</span>
      ),
    },
    {
      key: "a",
      header: "",
      cell: (client) => (
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setForm(fromClient(client))}>
            <Pencil className="h-3.5 w-3.5" /> Editar
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!client.active || deactivate.isPending}
            onClick={() => deactivate.mutate(client.id)}
          >
            <PowerOff className="h-3.5 w-3.5" /> Desativar
          </Button>
        </div>
      ),
    },
  ];

  return (
    <AppShell title="Clientes" subtitle="Base fixa reutilizada em ações e execuções">
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar por nome"
              className="pl-8"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <Select value={group} onValueChange={setGroup}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as listas</SelectItem>
              {groups.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="active">Ativos</SelectItem>
              <SelectItem value="inactive">Inativos</SelectItem>
            </SelectContent>
          </Select>
          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled
              title="Importação CSV será conectada em rodada posterior"
            >
              <Download className="h-4 w-4" /> Modelo CSV
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled
              title="Importação CSV pendente de fachada v1"
            >
              <Upload className="h-4 w-4" /> Importar CSV
            </Button>
            <Button size="sm" onClick={() => setForm(emptyForm)}>
              <Plus className="h-4 w-4" /> Novo cliente
            </Button>
          </div>
        </CardContent>
      </Card>

      <DataTable
        columns={columns}
        data={filtered}
        empty={clients.isLoading ? "Carregando clientes..." : "Nenhum cliente encontrado."}
      />

      <ClientDialog
        form={form}
        setForm={setForm}
        onSubmit={(input) => save.mutate(input)}
        saving={save.isPending}
      />
    </AppShell>
  );
}

function ClientDialog({
  form,
  setForm,
  onSubmit,
  saving,
}: {
  form: FormState | null;
  setForm: (form: FormState | null) => void;
  onSubmit: (form: FormState) => void;
  saving: boolean;
}) {
  if (!form) return null;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (form) onSubmit(form);
  }
  return (
    <Dialog open onOpenChange={(open) => !open && setForm(null)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{form.id ? "Editar cliente" : "Novo cliente"}</DialogTitle>
        </DialogHeader>
        <form className="grid gap-4 py-2" onSubmit={submit}>
          <div className="grid gap-2">
            <Label>Nome do cliente</Label>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label>Lista/grupo</Label>
            <Input
              value={form.group}
              onChange={(event) => setForm({ ...form, group: event.target.value })}
              required
            />
          </div>
          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <Label>Ativo</Label>
              <p className="text-xs text-muted-foreground">Incluir nas execuções em massa.</p>
            </div>
            <Switch
              checked={form.active}
              onCheckedChange={(active) => setForm({ ...form, active })}
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-2">
              <Label>Grupo</Label>
              <Input
                value={form.grupo}
                onChange={(event) => setForm({ ...form, grupo: event.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label>Cota</Label>
              <Input
                value={form.cota}
                onChange={(event) => setForm({ ...form, cota: event.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label>Versão</Label>
              <Input
                value={form.versao}
                onChange={(event) => setForm({ ...form, versao: event.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label>Observações</Label>
            <Textarea
              rows={2}
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button disabled={saving || !form.name}>
              {saving ? "Salvando..." : "Salvar cliente"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function fromClient(client: ApiClient): FormState {
  return {
    id: client.id,
    name: client.name,
    group: client.group,
    active: client.active,
    grupo: client.display_variables?.grupo || client.variables.grupo || "",
    cota: client.display_variables?.cota || client.variables.cota || "",
    versao: client.display_variables?.versao || client.variables.versao || "",
    notes: client.notes || "",
  };
}
