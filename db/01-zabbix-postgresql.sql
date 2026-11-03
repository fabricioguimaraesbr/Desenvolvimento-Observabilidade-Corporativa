-- =============================================================================
-- PostgreSQL 17 + TimescaleDB no DBxxx: usuário e banco do Zabbix
-- Rode como superusuário, conectado no banco "postgres":
--   psql -h DBxxx -U postgres -d postgres -v senha=troque -f db/01-zabbix-postgresql.sql
-- O schema (tabelas e hypertables) NÃO é criado aqui: quem cria é o job
-- zabbix-db-init da stack, rodado uma vez no servidor 1 (ver README).
-- =============================================================================
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE zabbix LOGIN PASSWORD %L', :'senha')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zabbix') \gexec

SELECT 'CREATE DATABASE zabbix OWNER zabbix ENCODING ''UTF8'' LC_COLLATE ''C.UTF-8'' LC_CTYPE ''C.UTF-8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'zabbix') \gexec

-- A extensão precisa de superusuário; o usuário zabbix só a usa
\c zabbix
CREATE EXTENSION IF NOT EXISTS timescaledb;
ALTER SCHEMA public OWNER TO zabbix;
