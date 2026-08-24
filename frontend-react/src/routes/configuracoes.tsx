import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { toast } from "sonner";
import {
  Wifi, Save, PlayCircle, KeyRound, Eraser, CornerDownLeft, ArrowRightToLine,
  Type, Shield, Database, DownloadCloud, Info,
} from "lucide-react";

export const Route = createFileRoute("/configuracoes")({
  head: () => ({ meta: [{ title: "Configurações — CotaSync" }] }),
  component: ConfigPage,
});

function ConfigPage() {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const notify = (msg: string) => toast.success(msg);

  return (
    <AppShell title="Configurações" subtitle="Configurações operacionais do CotaSync">
      <div className="grid max-w-4xl gap-4">
        {/* Sessão em destaque */}
        <Card className="border-success/40 bg-success/5">
          <CardContent className="grid gap-4 p-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-success/20 text-success">
                  <Wifi className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Sessão do sistema externo</p>
                  <p className="truncate text-base font-semibold text-foreground">Sessão conectada</p>
                </div>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Última verificação: agora · válida por aproximadamente 42 min.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => notify("Sessão testada com sucesso")}>
                <Shield className="h-4 w-4" /> Testar sessão
              </Button>
              <Button size="sm" onClick={() => notify("Abrindo sistema externo…")}>
                <PlayCircle className="h-4 w-4" /> Renovar acesso ao sistema externo
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 1. Sistema externo */}

        <Card>
          <CardHeader><CardTitle className="text-base">1. Sistema externo</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div><Label>Nome do sistema</Label><Input className="mt-1" defaultValue="Sistema Externo Consórcio" /></div>
            <div><Label>URL de login</Label><Input className="mt-1" defaultValue="https://sistema.externo/login" /></div>
            <div><Label>Host esperado</Label><Input className="mt-1" defaultValue="sistema.externo" /></div>
            <div><Label>Perfil de acesso</Label><Input className="mt-1" defaultValue="operador" /></div>
            <div className="sm:col-span-2 flex justify-end">
              <Button size="sm" onClick={() => notify("Configurações do sistema salvas")}>
                <Save className="h-4 w-4" /> Salvar alterações
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 2. Sessão do navegador */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">2. Sessão do navegador</CardTitle>
            <BadgeStatus tone="success"><Wifi className="mr-1 inline h-3 w-3" /> Conectada</BadgeStatus>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={() => notify("Abrindo sistema externo…")}>
              <PlayCircle className="h-4 w-4" /> Abrir sistema para login
            </Button>
            <Button variant="outline" onClick={() => notify("Sessão salva")}>
              <Save className="h-4 w-4" /> Salvar sessão
            </Button>
            <Button variant="outline" onClick={() => notify("Sessão testada com sucesso")}>
              <Shield className="h-4 w-4" /> Testar sessão
            </Button>
          </CardContent>
        </Card>

        {/* 3. Modo operador */}
        <Card>
          <CardHeader><CardTitle className="text-base">3. Modo operador para login</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-3 text-sm">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p className="text-foreground">
                A senha <span className="font-medium">não é salva</span>. Ela é enviada apenas para o campo ativo do navegador.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor="op-login">Texto / login</Label>
                <div className="mt-1 flex gap-2">
                  <Input id="op-login" value={login} onChange={(e) => setLogin(e.target.value)} placeholder="Digite o usuário" />
                  <Button size="sm" variant="outline" onClick={() => notify("Texto enviado ao campo ativo")}>
                    <Type className="h-4 w-4" />
                  </Button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">Envia como texto simples para o campo ativo.</p>
              </div>
              <div>
                <Label htmlFor="op-pass">Senha ou texto sensível</Label>
                <div className="mt-1 flex gap-2">
                  <Input id="op-pass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
                  <Button size="sm" variant="outline" onClick={() => { notify("Senha enviada ao campo ativo"); setPassword(""); }}>
                    <KeyRound className="h-4 w-4" />
                  </Button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">Não é armazenada em nenhum lugar.</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" onClick={() => notify("Texto digitado")}>
                <Type className="h-3.5 w-3.5" /> Digitar texto no campo ativo
              </Button>
              <Button size="sm" onClick={() => notify("Senha digitada")}>
                <KeyRound className="h-3.5 w-3.5" /> Digitar senha no campo ativo
              </Button>
              <Button size="sm" variant="outline"><ArrowRightToLine className="h-3.5 w-3.5" /> Tab</Button>
              <Button size="sm" variant="outline"><CornerDownLeft className="h-3.5 w-3.5" /> Enter</Button>
              <Button size="sm" variant="ghost"><Eraser className="h-3.5 w-3.5" /> Limpar campo ativo</Button>
            </div>
          </CardContent>
        </Card>

        {/* 4. Fila */}
        <Card>
          <CardHeader><CardTitle className="text-base">4. Configurações da fila</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <div>
              <Label>Delay padrão entre clientes (s)</Label>
              <Input className="mt-1" type="number" min={0} defaultValue={3} />
            </div>
            <div>
              <Label>Tempo máximo por execução (s)</Label>
              <Input className="mt-1" type="number" min={10} defaultValue={90} />
            </div>
            <div>
              <Label>Em caso de erro</Label>
              <Select defaultValue="continue">
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="continue">Continuar próxima linha</SelectItem>
                  <SelectItem value="pause">Pausar fila</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="sm:col-span-3 flex justify-end">
              <Button size="sm" onClick={() => notify("Configurações da fila salvas")}>
                <Save className="h-4 w-4" /> Salvar
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 5. Backup */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2"><Database className="h-4 w-4" /> 5. Backup</CardTitle>
            <BadgeStatus tone="success">Último backup: 2025-07-13 03:00</BadgeStatus>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">
              Gera um arquivo com clientes, ações e agendamentos. Recomendado antes de mudanças importantes.
            </p>
            <Button onClick={() => notify("Backup gerado com sucesso")}>
              <DownloadCloud className="h-4 w-4" /> Gerar backup
            </Button>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
