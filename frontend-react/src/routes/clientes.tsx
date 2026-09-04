import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, FileSpreadsheet, Pencil, Plus, PowerOff, Search, Upload } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  createClient,
  deactivateClient,
  exportClientsCsv,
  getClients,
  importClientsCsv,
  previewClientsCsv,
  updateClient,
  getSystemSpreadsheets,
  createSystemSpreadsheet,
  exportSystemSpreadsheet,
  importSystemSpreadsheetExcel,
  importSystemSpreadsheetGoogle,
  testGoogleSpreadsheet,
} from "@/services/api";
import type { ApiClient, ClientsCsvPreview, ClientsCsvPreviewRow, SystemSpreadsheet } from "@/types/api";

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

type PreviewRowWithId = ClientsCsvPreviewRow & { id: string };

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
  const dataSources = useQuery({ queryKey: ["system-spreadsheets"], queryFn: getSystemSpreadsheets });
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [status, setStatus] = useState("all");
  const [form, setForm] = useState<FormState | null>(null);
  const [csvDialogOpen, setCsvDialogOpen] = useState(false);
  const [csvFile, setCsvFile] = useState<{ name: string; text: string } | null>(null);
  const [csvPreview, setCsvPreview] = useState<ClientsCsvPreview | null>(null);
  const [spreadsheetDialogOpen, setSpreadsheetDialogOpen] = useState(false);
  const [spreadsheetName, setSpreadsheetName] = useState("");
  const [spreadsheetHeaders, setSpreadsheetHeaders] = useState("Nome,Grupo,Cota,Versão");
  const [spreadsheetMode, setSpreadsheetMode] = useState<"create" | "excel" | "google">("create");
  const [excelUpload, setExcelUpload] = useState<{ filename: string; content_base64: string } | null>(null);
  const [googleUrl, setGoogleUrl] = useState("");
  const [googleTabs, setGoogleTabs] = useState<string[]>([]);
  const [googleTab, setGoogleTab] = useState("");
  const createSpreadsheet = useMutation({
    mutationFn: () => createSystemSpreadsheet({ name: spreadsheetName, headers: spreadsheetHeaders.split(",").map((value) => value.trim()).filter(Boolean) }),
    onSuccess: () => { setSpreadsheetDialogOpen(false); setSpreadsheetName(""); void queryClient.invalidateQueries({ queryKey: ["system-spreadsheets"] }); toast.success("Planilha do Sistema criada."); },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível criar a planilha."),
  });
  const importExcel = useMutation({ mutationFn: () => { if (!excelUpload) throw new Error("Selecione um arquivo .xlsx."); return importSystemSpreadsheetExcel({ name: spreadsheetName || excelUpload.filename, ...excelUpload }); }, onSuccess: () => { setSpreadsheetDialogOpen(false); void queryClient.invalidateQueries({ queryKey: ["system-spreadsheets"] }); toast.success("Excel importado para a Planilha do Sistema."); }, onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível importar o Excel.") });
  const testGoogle = useMutation({ mutationFn: () => testGoogleSpreadsheet(googleUrl), onSuccess: (result) => { setGoogleTabs(result.tabs); setGoogleTab(result.tabs[0] || ""); toast.success(`Planilha encontrada: ${result.name}`); }, onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível conectar ao Google Sheets.") });
  const importGoogle = useMutation({ mutationFn: () => importSystemSpreadsheetGoogle({ name: spreadsheetName || "Planilha Google", url_or_id: googleUrl, tab: googleTab }), onSuccess: () => { setSpreadsheetDialogOpen(false); void queryClient.invalidateQueries({ queryKey: ["system-spreadsheets"] }); toast.success("Google Sheets importado para a Planilha do Sistema."); }, onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível importar a aba Google.") });

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

  const previewCsv = useMutation({
    mutationFn: async () => {
      if (!csvFile) throw new Error("Selecione um arquivo CSV.");
      return previewClientsCsv({ filename: csvFile.name, csvText: csvFile.text });
    },
    onSuccess: (preview) => setCsvPreview(preview),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível validar o CSV."),
  });

  const importCsv = useMutation({
    mutationFn: async () => {
      if (!csvFile) throw new Error("Selecione um arquivo CSV.");
      return importClientsCsv({ filename: csvFile.name, csvText: csvFile.text });
    },
    onSuccess: (result) => {
      toast.success(`${result.count} clientes importados.`);
      setCsvDialogOpen(false);
      setCsvFile(null);
      setCsvPreview(null);
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível importar o CSV."),
  });

  const exportCsv = useMutation({
    mutationFn: exportClientsCsv,
    onSuccess: (csvText) => downloadCsv("clientes_cotasync.csv", csvText),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível exportar clientes."),
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
            <Button variant="outline" size="sm" onClick={() => exportCsv.mutate()}>
              <Download className="h-4 w-4" /> Exportar CSV
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCsvDialogOpen(true)}>
              <Upload className="h-4 w-4" /> Importar CSV
            </Button>
            <Button size="sm" onClick={() => setForm(emptyForm)}>
              <Plus className="h-4 w-4" /> Novo cliente
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card className="mb-4">
        <CardContent className="space-y-3 p-4">
          <div>
            <p className="text-sm font-medium">Planilhas do sistema</p>
            <p className="text-xs text-muted-foreground">A representação canônica de clientes, campos e resultados.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setSpreadsheetDialogOpen(true)}><Plus className="h-4 w-4" /> Nova planilha</Button>
            {(dataSources.data || []).map((sheet: SystemSpreadsheet) => <div key={sheet.id} className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"><FileSpreadsheet className="h-4 w-4" /><span>{sheet.name} · {sheet.client_count} clientes · {sheet.fields.length} campos</span><span className="text-xs text-muted-foreground">{sheet.connectors.map((connector) => connector.type === "google_sheets" ? "Google Sheets" : "Excel").join(" + ") || "CotaSync"}</span><Button size="sm" variant="ghost" onClick={async () => { const blob = await exportSystemSpreadsheet(sheet.id); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `${sheet.name}.xlsx`; link.click(); URL.revokeObjectURL(url); }}>Baixar Excel</Button></div>)}
          </div>
        </CardContent>
      </Card>

      <Dialog open={spreadsheetDialogOpen} onOpenChange={setSpreadsheetDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Nova planilha</DialogTitle></DialogHeader>
          <div className="grid gap-3"><div className="grid grid-cols-3 gap-2"><Button variant={spreadsheetMode === "excel" ? "default" : "outline"} onClick={() => setSpreadsheetMode("excel")}>Importar Excel</Button><Button variant={spreadsheetMode === "google" ? "default" : "outline"} onClick={() => setSpreadsheetMode("google")}>Google Sheets</Button><Button variant={spreadsheetMode === "create" ? "default" : "outline"} onClick={() => setSpreadsheetMode("create")}>Criar no CotaSync</Button></div><div className="grid gap-2"><Label>Nome da Planilha do Sistema</Label><Input placeholder="Clientes Setembro" value={spreadsheetName} onChange={(event) => setSpreadsheetName(event.target.value)} /></div>{spreadsheetMode === "create" && <Input value={spreadsheetHeaders} onChange={(event) => setSpreadsheetHeaders(event.target.value)} placeholder="Campos separados por vírgula" />}{spreadsheetMode === "excel" && <Input type="file" accept=".xlsx" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; const encoded = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = () => reject(new Error("Falha ao ler arquivo.")); reader.readAsDataURL(file); }); setExcelUpload({ filename: file.name, content_base64: encoded }); }} />}{spreadsheetMode === "google" && <><Input placeholder="URL ou ID da planilha Google" value={googleUrl} onChange={(event) => setGoogleUrl(event.target.value)} /><Button variant="outline" onClick={() => testGoogle.mutate()} disabled={!googleUrl.trim() || testGoogle.isPending}>Testar conexão</Button>{googleTabs.length > 0 && <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={googleTab} onChange={(event) => setGoogleTab(event.target.value)}>{googleTabs.map((tab) => <option key={tab} value={tab}>{tab}</option>)}</select>}</>}</div>
          <DialogFooter><Button onClick={() => spreadsheetMode === "create" ? createSpreadsheet.mutate() : spreadsheetMode === "excel" ? importExcel.mutate() : importGoogle.mutate()} disabled={!spreadsheetName.trim() || (spreadsheetMode === "excel" ? !excelUpload : spreadsheetMode === "google" ? !googleTab : false)}>{spreadsheetMode === "create" ? "Criar planilha" : "Importar para o sistema"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

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
      <CsvImportDialog
        open={csvDialogOpen}
        onOpenChange={(open) => {
          setCsvDialogOpen(open);
          if (!open) {
            setCsvFile(null);
            setCsvPreview(null);
          }
        }}
        csvFile={csvFile}
        setCsvFile={(file) => {
          setCsvFile(file);
          setCsvPreview(null);
        }}
        preview={csvPreview}
        previewing={previewCsv.isPending}
        importing={importCsv.isPending}
        onPreview={() => previewCsv.mutate()}
        onImport={() => importCsv.mutate()}
      />
    </AppShell>
  );
}

function CsvImportDialog({
  open,
  onOpenChange,
  csvFile,
  setCsvFile,
  preview,
  previewing,
  importing,
  onPreview,
  onImport,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  csvFile: { name: string; text: string } | null;
  setCsvFile: (file: { name: string; text: string } | null) => void;
  preview: ClientsCsvPreview | null;
  previewing: boolean;
  importing: boolean;
  onPreview: () => void;
  onImport: () => void;
}) {
  const previewColumns: Column<PreviewRowWithId>[] = [
    { key: "line", header: "Linha", cell: (row) => row.row_number },
    { key: "name", header: "Nome", cell: (row) => row.name || "-" },
    { key: "group", header: "Lista/grupo", cell: (row) => row.group || "-" },
    { key: "grupo", header: "Grupo", cell: (row) => row.display_variables.grupo || "-" },
    { key: "cota", header: "Cota", cell: (row) => row.display_variables.cota || "-" },
    { key: "versao", header: "Versão", cell: (row) => row.display_variables.versao || "-" },
    {
      key: "status",
      header: "Estado",
      cell: (row) => (
        <BadgeStatus tone={row.valid ? "success" : "error"}>
          {row.valid ? (row.operation === "update" ? "Atualização" : "Novo") : "Corrigir"}
        </BadgeStatus>
      ),
    },
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Importar clientes por CSV</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <Alert>
            <AlertTitle>Preview obrigatório</AlertTitle>
            <AlertDescription>
              Limites: CSV UTF-8, até 1 MB e 1000 linhas. Headers aceitos: id, name, group, active,
              grupo, cota, versao e notes.
            </AlertDescription>
          </Alert>
          <div className="grid gap-2">
            <Label>Arquivo CSV</Label>
            <Input
              type="file"
              accept=".csv,text/csv"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) {
                  setCsvFile(null);
                  return;
                }
                setCsvFile({ name: file.name, text: await file.text() });
              }}
            />
            {csvFile && (
              <p className="text-xs text-muted-foreground">
                {csvFile.name} · {new Blob([csvFile.text]).size} bytes
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={!csvFile || previewing} onClick={onPreview}>
              {previewing ? "Validando..." : "Gerar preview"}
            </Button>
            <Button disabled={!preview?.can_import || importing} onClick={onImport}>
              {importing ? "Importando..." : "Confirmar importação"}
            </Button>
          </div>
          {preview && (
            <>
              <div className="grid gap-2 text-sm sm:grid-cols-5">
                <CsvMetric label="Linhas" value={preview.total_rows} />
                <CsvMetric label="Válidas" value={preview.valid_rows} />
                <CsvMetric label="Inválidas" value={preview.invalid_rows} />
                <CsvMetric label="Novos" value={preview.new_clients} />
                <CsvMetric label="Atualizações" value={preview.updates} />
              </div>
              {preview.conflicts.length > 0 && (
                <Alert variant="destructive">
                  <AlertTitle>Conflitos encontrados</AlertTitle>
                  <AlertDescription>
                    {preview.conflicts.slice(0, 5).map((conflict) => (
                      <p key={`${conflict.row_number}-${conflict.field}`}>
                        Linha {conflict.row_number}: {conflict.message}
                      </p>
                    ))}
                  </AlertDescription>
                </Alert>
              )}
              {preview.warnings.length > 0 && (
                <Alert>
                  <AlertTitle>Avisos</AlertTitle>
                  <AlertDescription>
                    {preview.warnings.map((warning) => (
                      <p key={warning.code}>{warning.message}</p>
                    ))}
                  </AlertDescription>
                </Alert>
              )}
              <DataTable
                columns={previewColumns}
                data={preview.rows.map((row) => ({ id: String(row.row_number), ...row }))}
                empty="Nenhuma linha para mostrar."
              />
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CsvMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold text-foreground">{value}</p>
    </div>
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

function downloadCsv(filename: string, csvText: string) {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
