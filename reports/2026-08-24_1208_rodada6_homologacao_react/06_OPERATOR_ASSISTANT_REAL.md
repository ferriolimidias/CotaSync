# OperatorAssistant Real

Funcionalidades mantidas: texto normal, modo sensível, limpar campo ativo, Tab, Enter e marcação de variáveis `grupo`, `cota`, `versao`.

Alteração: o comando `Inserir + Tab` agora aguarda a inserção terminar antes de enviar Tab, evitando corrida entre chamadas.

Modo sensível: o valor fica apenas no estado local do componente e é limpo após inserção. A API remove `value`/`text` da resposta sensível.

Não concluído: homologação manual de inserção em campo real do sistema externo. Não foi digitada senha nem dado sensível real.
