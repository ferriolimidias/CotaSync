# Users e Auth

Contagem no banco: 2 users.

Conclusão: autenticação passou a consultar `users` no PostgreSQL e invalida usuário inativo.
Evidência: `backend/services/auth.py`, login/me/logout com teste verde, `gh auth status` apenas para GitHub.
Estado: funcional.
Impacto: admin/operator saem do env como fonte normal e viram dados operacionais.

Conclusão: bootstrap do primeiro usuário só ocorre com senha configurada correta.
Evidência: checagem de senha no bootstrap e hash PBKDF2.
Estado: corrigido.
Impacto: evita criar admin com credencial errada quando o banco está vazio.
