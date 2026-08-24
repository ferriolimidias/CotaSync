import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  Users,
  Zap,
  GraduationCap,
  ListChecks,
  CalendarClock,
  FileBarChart2,
  Settings,
  Stethoscope,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
} from "@/components/ui/sidebar";

const nav = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard },
  { title: "Clientes", url: "/clientes", icon: Users },
  { title: "Ações", url: "/acoes", icon: Zap },
  { title: "Ensinar ação", url: "/ensinar-acao", icon: GraduationCap },
  { title: "Execução em massa", url: "/execucao", icon: ListChecks },
  { title: "Agendamentos", url: "/agendamentos", icon: CalendarClock },
  { title: "Relatórios", url: "/relatorios", icon: FileBarChart2 },
  { title: "Configurações", url: "/configuracoes", icon: Settings },
];

const secondaryNav = [
  { title: "Diagnóstico técnico", url: "/diagnostico", icon: Stethoscope },
];

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="border-b border-sidebar-border">
        <Link to="/" className="flex items-center gap-2 px-2 py-2">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
            <span className="text-sm font-bold">CS</span>
          </div>
          <div className="min-w-0 group-data-[collapsible=icon]:hidden">
            <p className="truncate text-sm font-semibold text-sidebar-foreground">CotaSync</p>
            <p className="truncate text-[10px] text-sidebar-foreground/60">Automação inteligente</p>
          </div>
        </Link>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Operação</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {nav.map((item) => (
                <SidebarMenuItem key={item.url}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname === item.url}
                    tooltip={item.title}
                  >
                    <Link to={item.url}>
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="mt-auto">
          <SidebarGroupLabel className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40">
            Suporte
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {secondaryNav.map((item) => (
                <SidebarMenuItem key={item.url}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname === item.url}
                    tooltip={item.title}
                    className="text-sidebar-foreground/70 hover:text-sidebar-foreground"
                  >
                    <Link to={item.url}>
                      <item.icon className="h-4 w-4" />
                      <span className="text-xs">{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>


      <SidebarFooter className="border-t border-sidebar-border">
        <div className="px-2 py-2 text-[10px] text-sidebar-foreground/60 group-data-[collapsible=icon]:hidden">
          v0.1 · Front-end mock
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
