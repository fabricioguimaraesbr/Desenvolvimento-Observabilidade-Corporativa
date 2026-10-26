-- Usuário somente leitura para o Catálogo de Monitoramento.
-- Rode como superusuário (ou dono do banco) no banco do Zabbix:
--   docker exec -i <container-postgres> psql -U zabbix -d zabbix < sql/01-usuario-somente-leitura.sql
-- Troque a senha antes de executar.

CREATE ROLE zbx_catalogo LOGIN PASSWORD 'troque-esta-senha'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

ALTER ROLE zbx_catalogo SET default_transaction_read_only = on;
ALTER ROLE zbx_catalogo SET statement_timeout = '10min';
ALTER ROLE zbx_catalogo CONNECTION LIMIT 3;

GRANT CONNECT ON DATABASE zabbix TO zbx_catalogo;
GRANT USAGE ON SCHEMA public TO zbx_catalogo;

-- Apenas as tabelas de configuração usadas pelo coletor.
-- Nenhuma tabela de histórico/tendência (history*, trends*) é liberada.
GRANT SELECT ON
  dbversion, hosts, hstgrp, hosts_groups, hosts_templates, host_tag, hostmacro,
  interface, proxy, items, item_rtdata, item_tag, triggers, functions
TO zbx_catalogo;

-- Observação: a coluna hostmacro.value só é lida para macros do tipo texto
-- (type = 0). Se preferir não expor macros, remova "hostmacro" acima; o
-- coletor seguirá funcionando sem as regras por macro.
