import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { toast } from "sonner";
import {
  Check, ChevronRight, Circle, Monitor, CornerDownLeft, ArrowRightToLine,
  Eraser, Send, Sparkles, Play, Calendar, ListChecks, ArrowLeft, CheckCircle2,
  GripVertical, Minus, Maximize2, Pause, X, CircleDot,
} from "lucide-react";
import { cn } from "@/lib/utils";


export const Route = createFileRoute("/ensinar-acao")({
  head: () => ({ meta: [{ title: "Ensinar ação — CotaSync" }] }),
  component: EnsinarPage,
});

const steps = ["Dados da ação", "Ensinar no navegador", "Finalizar e testar", "Ação pronta"];

const SUGGESTIONS = ["grupo", "cota", "versao", "cpf", "contrato", "codigo"];

function EnsinarPage() {
  const [step, setStep] = useState(0);

  return (
    <AppShell title="Ensinar ação" subtitle="Fluxo guiado para criar uma nova ação">
      {/* Stepper */}
      <div className="mb-6 flex items-center gap-2 overflow-x-auto">
        {steps.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <button
              onClick={() => setStep(i)}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                i === step
                  ? "border-primary bg-primary/10 text-primary"
                  : i < step
                    ? "border-border bg-muted/60 text-foreground"
                    : "border-dashed border-border text-muted-foreground hover:bg-muted/40",
              )}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-background text-[10px]">
                {i < step ? <Check className="h-3 w-3 text-primary" /> : i === step ? <Circle className="h-2 w-2 fill-primary text-primary" /> : i + 1}
              </span>
              {s}
            </button>
            {i < steps.length - 1 && <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          </div>
        ))}
      </div>

      {step === 0 && <Step1 onNext={() => setStep(1)} />}
      {step === 1 && <Step2 onBack={() => setStep(0)} onNext={() => setStep(2)} />}
      {step === 2 && <Step3 onBack={() => setStep(1)} onNext={() => setStep(3)} />}
      {step === 3 && <Step4 onRestart={() => setStep(0)} />}
    </AppShell>
  );
}

/* ---------- Step 1 ---------- */
function Step1({ onNext }: { onNext: () => void }) {
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle className="text-base">Dados da ação</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="a-name">Nome da ação</Label>
          <Input id="a-name" placeholder="Ex.: Número de parcelas pagas" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="a-return">O que essa ação deve retornar?</Label>
          <Textarea id="a-return" rows={3} placeholder="Ex.: A quantidade de parcelas já pagas pelo cliente." />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="a-vars">Variáveis esperadas (opcional)</Label>
          <Input id="a-vars" placeholder="Ex.: grupo, cota, versao" />
          <p className="text-xs text-muted-foreground">
            Você poderá marcar variáveis diretamente durante o ensino.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <p className="text-xs text-muted-foreground">Ao começar, o navegador abre e a gravação inicia automaticamente.</p>
          <Button onClick={onNext}><Play className="h-4 w-4" /> Começar ensino</Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ---------- Step 2 ---------- */
function Step2({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const [paused, setPaused] = useState(false);

  return (
    <div className="relative">
      {/* Header with recording status */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn(
            "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
            paused
              ? "border-warning/40 bg-warning/15 text-warning-foreground"
              : "border-destructive/40 bg-destructive/10 text-destructive"
          )}>
            <CircleDot className={cn("h-3 w-3", !paused && "animate-pulse")} />
            {paused ? "Gravação pausada" : "Gravação ativa"}
          </span>
          <span className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">7</span> passos gravados ·{" "}
            <span className="font-medium text-foreground">3</span> variáveis identificadas
          </span>
        </div>
        <span className="text-xs text-muted-foreground">
          Dica: clique num campo do navegador antes de inserir um valor.
        </span>
      </div>

      {/* Browser (large) with floating assistant overlay */}
      <div className="relative">
        <Card className="min-h-[560px] overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-2">
            <div className="flex gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />
              <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />
              <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />
            </div>
            <div className="ml-2 flex-1 truncate rounded bg-background px-3 py-1 text-xs text-muted-foreground">
              sistema-externo.exemplo.com/consulta
            </div>
          </div>
          <div className="flex min-h-[500px] flex-col items-center justify-center gap-3 bg-muted/20 p-6 text-center">
            <Monitor className="h-12 w-12 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">Navegador do sistema externo</p>
            <p className="max-w-md text-xs text-muted-foreground">
              Clique nos campos da tela para posicionar o cursor. Use o assistente flutuante para preencher valores e navegar.
            </p>
          </div>
        </Card>

        {/* Floating assistant */}
        <FloatingAssistant />
      </div>

      {/* Bottom action bar */}
      <div className="sticky bottom-0 mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-background/95 p-3 shadow-lg backdrop-blur">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <X className="h-4 w-4" /> Cancelar ensino
        </Button>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setPaused((p) => !p);
              toast.success(paused ? "Gravação retomada" : "Gravação pausada");
            }}
          >
            <Pause className="h-4 w-4" /> {paused ? "Retomar gravação" : "Pausar gravação"}
          </Button>
          <Button size="sm" onClick={onNext}>
            <Check className="h-4 w-4" /> Finalizar ensino
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ---------- Floating Assistant ---------- */
function FloatingAssistant() {
  const [collapsed, setCollapsed] = useState(false);
  const [pos, setPos] = useState({ x: 24, y: 24 });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragState = useRef<{ dx: number; dy: number; dragging: boolean }>({ dx: 0, dy: 0, dragging: false });

  const [text, setText] = useState("");
  const [isVar, setIsVar] = useState(false);
  const [varName, setVarName] = useState("");

  const notify = (m: string) => toast.success(m);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragState.current.dragging) return;
      setPos({ x: e.clientX - dragState.current.dx, y: e.clientY - dragState.current.dy });
    };
    const onUp = () => (dragState.current.dragging = false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const startDrag = (e: React.MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragState.current = { dx: e.clientX - rect.left, dy: e.clientY - rect.top, dragging: true };
  };

  return (
    <div
      ref={containerRef}
      className="absolute z-20 w-[300px] select-none rounded-lg border border-border bg-card shadow-2xl"
      style={{ top: pos.y, right: pos.x }}
    >
      {/* Header (drag handle) */}
      <div
        onMouseDown={startDrag}
        className="flex cursor-grab items-center gap-2 rounded-t-lg border-b border-border bg-muted/60 px-2 py-1.5 active:cursor-grabbing"
      >
        <GripVertical className="h-3.5 w-3.5 text-muted-foreground" />
        <p className="flex-1 text-xs font-semibold text-foreground">Assistente de preenchimento</p>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label={collapsed ? "Expandir" : "Recolher"}
        >
          {collapsed ? <Maximize2 className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />}
        </button>
      </div>

      {!collapsed && (
        <div className="grid gap-3 p-3">
          <div className="grid gap-1.5">
            <Label htmlFor="fa-val" className="text-xs">Texto para inserir</Label>
            <Input id="fa-val" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ex.: 935" className="h-8 text-sm" />
          </div>

          <label className="flex items-center gap-2 text-xs">
            <Checkbox checked={isVar} onCheckedChange={(v) => setIsVar(v === true)} />
            Este valor é uma variável
          </label>

          {isVar && (
            <div className="grid gap-1.5">
              <Label htmlFor="fa-var" className="text-xs">Nome da variável</Label>
              <Input id="fa-var" value={varName} onChange={(e) => setVarName(e.target.value)} placeholder="grupo" className="h-8 text-sm" />
              <div className="flex flex-wrap gap-1 pt-0.5">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setVarName(s)}
                    className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-foreground hover:bg-muted"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-1.5 pt-1">
            <Button size="sm" className="col-span-2 h-8" onClick={() => notify("Inserido no campo ativo")}>
              <Send className="h-3.5 w-3.5" /> Inserir no campo ativo
            </Button>
            <Button size="sm" variant="secondary" className="col-span-2 h-8" onClick={() => notify("Inserido e avançado")}>
              <ArrowRightToLine className="h-3.5 w-3.5" /> Inserir e avançar com Tab
            </Button>
            <Button size="sm" variant="outline" className="h-8" onClick={() => notify("Tab enviado")}>
              <ArrowRightToLine className="h-3.5 w-3.5" /> Tab
            </Button>
            <Button size="sm" variant="outline" className="h-8" onClick={() => notify("Enter enviado")}>
              <CornerDownLeft className="h-3.5 w-3.5" /> Enter
            </Button>
            <Button size="sm" variant="ghost" className="col-span-2 h-8" onClick={() => notify("Campo limpo")}>
              <Eraser className="h-3.5 w-3.5" /> Limpar campo ativo
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}


/* ---------- Step 3 ---------- */
function Step3({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const items = [
    { label: "Caminho aprendido", value: "OK", tone: "success" as const },
    { label: "Variáveis", value: "grupo, cota, versao", tone: "info" as const },
    { label: "Teste da ação", value: "OK", tone: "success" as const },
    { label: "Resultado detectado", value: "032", tone: "success" as const },
  ];

  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {items.map((it) => (
          <Card key={it.label}>
            <CardContent className="p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">{it.label}</p>
              <div className="mt-2 flex items-center gap-2">
                <BadgeStatus tone={it.tone}>{it.value}</BadgeStatus>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="grid gap-4 p-5">
          <p className="text-sm text-muted-foreground">
            A ação pode ser usada quando o caminho foi testado e o resultado foi confirmado.
            A revisão com IA é apenas uma ajuda adicional.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button><Check className="h-4 w-4" /> Confirmar este resultado</Button>
            <Button variant="outline">Selecionar outro resultado na tela</Button>
            <Button variant="outline">Ver candidatos avançados</Button>
            <Button variant="ghost"><Sparkles className="h-4 w-4" /> Revisar com IA (opcional)</Button>
          </div>
          <div className="flex justify-between pt-2">
            <Button variant="ghost" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Voltar</Button>
            <Button onClick={onNext}>Concluir</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ---------- Step 4 ---------- */
function Step4({ onRestart }: { onRestart: () => void }) {
  return (
    <Card className="max-w-2xl">
      <CardContent className="grid gap-4 p-8 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[var(--success)]/15 text-[var(--success)]">
          <CheckCircle2 className="h-8 w-8" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-foreground">Ação pronta para uso</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Sua ação foi ensinada, testada e confirmada. Você já pode utilizá-la em execuções e agendamentos.
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2 pt-2">
          <Button><Play className="h-4 w-4" /> Executar agora</Button>
          <Button variant="outline" asChild>
            <Link to="/execucao"><ListChecks className="h-4 w-4" /> Usar em execução em massa</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to="/agendamentos"><Calendar className="h-4 w-4" /> Criar agendamento</Link>
          </Button>
          <Button variant="ghost" asChild>
            <Link to="/acoes"><ArrowLeft className="h-4 w-4" /> Voltar para ações</Link>
          </Button>
        </div>
        <button onClick={onRestart} className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:underline">
          Ensinar outra ação
        </button>
      </CardContent>
    </Card>
  );
}
