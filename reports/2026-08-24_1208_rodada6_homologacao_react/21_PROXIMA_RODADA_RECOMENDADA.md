# Próxima Rodada Recomendada

Rodada 7: homologação assistida com operador presente no sistema externo real.

Escopo recomendado: login manual externo pelo React, ensinar uma consulta segura ponta a ponta, confirmar resultado, publicar, executar individualmente, rodar lote pequeno, testar cancel-after-current e validar `quantidade-de-parcelas` sem inventar URL.

Critério de saída: se essa homologação real passar, remover `frontend/` Streamlit, serviço `cotasync_test_frontend`, dependências exclusivas e endpoints HTTP legados sem consumidor.
