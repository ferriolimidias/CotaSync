# Build Frontend Decisão

Modelo observado: TanStack Start gera client, SSR e Nitro (`.output/server`), com preset Cloudflare module e runtime.

Decisão: nesta rodada, manter runtime Bun/TanStack em staging. Servir apenas `.output/public` por Nginx como SPA estática não foi escolhido porque o build atual contém SSR/Nitro e o servidor `serve.mjs` já faz proxy same-origin `/api`.

Build: `bun run build` passou.

Warnings de build: aviso sobre `vite-tsconfig-paths` agora nativo no Vite e aviso Nitro `inlineDynamicImports`; sem erro funcional.
