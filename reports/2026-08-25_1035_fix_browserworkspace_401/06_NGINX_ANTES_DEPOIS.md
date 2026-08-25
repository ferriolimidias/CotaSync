# Nginx Antes Depois

Arquivo real auditado:
- `/etc/nginx/sites-enabled/desktop-cotasync.ferriolimidias.com.br`.

Template versionado:
- `deploy/nginx/desktop-cotasync.ferriolimidias.com.br.conf`.

Antes:
```nginx
proxy_pass http://127.0.0.1:8100/api/desktop-browser/validate-view-token;
```

Depois:
```nginx
proxy_pass http://127.0.0.1:8100/api/v1/browser/validate-view-token;
```

Mantido:
- `internal`.
- `auth_request`.
- `proxy_pass_request_body off`.
- Header `X-Desktop-View-Token`.
- `access_log off`.
- `Cache-Control no-store`.
- `Referrer-Policy no-referrer`.
- `X-Content-Type-Options nosniff`.

Validacao:
- `sudo nginx -t`: sucesso.
- `sudo systemctl reload nginx`: executado apos teste de sintaxe.

