# Nginx Antes/Depois

## Antes

Arquivo auditado:

- `/etc/nginx/sites-available/cotasync.ferriolimidias.com.br`
- `/etc/nginx/sites-enabled/cotasync.ferriolimidias.com.br` -> symlink para o arquivo acima

Conteudo anterior do dominio principal:

```nginx
server {
    server_name cotasync.ferriolimidias.com.br;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:3100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600;
        proxy_send_timeout 600;
    }

    listen [::]:443 ssl; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/cotasync.ferriolimidias.com.br/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/cotasync.ferriolimidias.com.br/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

}
server {
    if ($host = cotasync.ferriolimidias.com.br) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    listen 80;
    listen [::]:80;
    server_name cotasync.ferriolimidias.com.br;
    return 404; # managed by Certbot


}
```

Comportamento anterior validado: `https://cotasync.ferriolimidias.com.br/` entregava HTML do Streamlit.

## Depois

Configuracao aplicada:

```nginx
server {
    server_name cotasync.ferriolimidias.com.br;

    client_max_body_size 50M;

    location /api/ {
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600;
        proxy_send_timeout 600;
    }

    location / {
        proxy_pass http://127.0.0.1:3300;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600;
        proxy_send_timeout 600;
    }

    listen [::]:443 ssl; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/cotasync.ferriolimidias.com.br/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/cotasync.ferriolimidias.com.br/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

}
server {
    if ($host = cotasync.ferriolimidias.com.br) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    listen 80;
    listen [::]:80;
    server_name cotasync.ferriolimidias.com.br;
    return 404; # managed by Certbot


}
```

Validacao:

- `sudo nginx -t`: sucesso.
- `sudo systemctl reload nginx`: sucesso.
