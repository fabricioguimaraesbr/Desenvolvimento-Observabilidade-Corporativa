-- =============================================================================
-- Banco do Grafana no DBxxx (compartilhado pelos 3 servidores)
--   psql -h DBxxx -U postgres -d postgres -v senha=troque -f db/02-grafana-postgresql.sql
-- O Grafana cria as próprias tabelas na primeira subida.
-- =============================================================================
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE grafana LOGIN PASSWORD %L', :'senha')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana') \gexec

SELECT 'CREATE DATABASE grafana OWNER grafana ENCODING ''UTF8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'grafana') \gexec

\c grafana
ALTER SCHEMA public OWNER TO grafana;
