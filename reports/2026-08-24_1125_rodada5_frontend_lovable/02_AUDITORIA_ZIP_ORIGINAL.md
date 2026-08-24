# Auditoria ZIP Original

ZIP: `/home/joseadmin/front.zip`.

Estrutura encontrada sem diretório raiz aninhado: `package.json`, `src/`, configs, `bun.lock`, `vite.config.ts`, shadcn/ui, TanStack Router/Start, Tailwind 4, React 19.

Não encontrados: `node_modules/`, `dist/`, `.env`, `.env.local`, `.env.production`, Supabase, Firebase ou secrets.

Scripts auditados antes de executar: `dev`, `build`, `build:dev`, `preview`, `lint`, `format`. Não havia `preinstall`/`postinstall`.

Package manager identificado: Bun por `bun.lock`.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

