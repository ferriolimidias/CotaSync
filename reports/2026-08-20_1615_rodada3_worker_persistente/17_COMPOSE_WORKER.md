# Compose Worker

Arquivo: `docker-compose.test.yml`
Classe/função: serviço `cotasync_test_worker`
Antes: compose de teste tinha backend, frontend, postgres e desktop browser.
Depois: adiciona worker sem porta publicada.
Motivo: processo separado para execução de batches.
Banco/estado afetado: usa `DATABASE_URL` do `cotasync_test_postgres`.
Transação: não aplicável.
Recovery: `restart: unless-stopped`.
Teste: `docker compose -f docker-compose.test.yml up -d --build cotasync_test_worker`.
Resultado: container `cotasync_test_worker` iniciado e heartbeat `idle`.
Risco restante: imagem expõe portas por Dockerfile, mas serviço worker não faz bind em host.

Arquivo: `docker-compose.yml`
Depois: separa `cotasync_backend`, `cotasync_worker`, `cotasync_frontend`.
