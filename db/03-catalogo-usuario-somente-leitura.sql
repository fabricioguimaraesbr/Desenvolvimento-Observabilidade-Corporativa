-- Usuário somente leitura para o Catálogo de Monitoramento (Zabbix 7.x e 8.0).
--
-- IMPORTANTE: rode CONECTADO NO BANCO DO ZABBIX (não no banco "postgres"):
--   psql -h <DBxxx> -U <admin> -d <banco-do-zabbix> -v senha=troque-esta-senha -f db/03-catalogo-usuario-somente-leitura.sql
-- Em psql interativo: \c <banco-do-zabbix> antes de executar.

\set ON_ERROR_STOP on

-- Para logo se a sessão não estiver no banco do Zabbix
DO $$
BEGIN
  IF to_regclass('public.dbversion') IS NULL THEN
    RAISE EXCEPTION 'Conectado em "%", que não é o banco do Zabbix. Use \c <banco-do-zabbix> e rode de novo.',
      current_database();
  END IF;
END $$;

-- Cria o usuário só se ainda não existir (pode rodar o script mais de uma vez)
SELECT format('CREATE ROLE zbx_catalogo LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', :'senha')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zbx_catalogo') \gexec

ALTER ROLE zbx_catalogo SET default_transaction_read_only = on;
ALTER ROLE zbx_catalogo SET statement_timeout = '10min';
ALTER ROLE zbx_catalogo CONNECTION LIMIT 5;

SELECT format('GRANT CONNECT ON DATABASE %I TO zbx_catalogo', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO zbx_catalogo;

-- Apenas as tabelas de configuração usadas pelo coletor. Nenhuma tabela de
-- histórico/tendência (history*, trends*) é liberada. Tabelas que não existem na
-- versão instalada são ignoradas (trigger_rtdata só existe a partir do 8.0).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['dbversion', 'hosts', 'hstgrp', 'hosts_groups', 'hosts_templates', 'host_tag',
                           'hostmacro', 'interface', 'proxy', 'proxy_group', 'items', 'item_rtdata',
                           'item_tag', 'triggers', 'trigger_rtdata', 'functions'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT ON public.%I TO zbx_catalogo', t);
    ELSE
      RAISE NOTICE 'tabela % não existe nesta versão do Zabbix, ignorada', t;
    END IF;
  END LOOP;
END $$;

-- Observação: a coluna hostmacro.value só é lida para macros do tipo texto
-- (type = 0). Se preferir não expor macros, revogue o acesso a hostmacro; o
-- coletor seguirá funcionando sem as regras por macro.
