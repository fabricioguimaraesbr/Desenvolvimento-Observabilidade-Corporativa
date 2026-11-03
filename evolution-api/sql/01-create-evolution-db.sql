-- =============================================================================
-- Evolution API - preparação no PostgreSQL corporativo
-- -----------------------------------------------------------------------------
-- Executar como superusuário (ou role com CREATEROLE/CREATEDB), ex.:
--   psql -h HOST_POSTGRES -U postgres -f 01-create-evolution-db.sql
--
-- Cria usuário e database DEDICADOS para a Evolution API, isolados dos dados
-- dos ABX. A própria Evolution cria as tabelas (migrations Prisma) no schema
-- "evolution_api" na primeira inicialização.
--
-- ANTES DE EXECUTAR: troque ALTERAR_SENHA_FORTE pela senha definitiva
-- (a mesma que irá no DATABASE_CONNECTION_URI do .env).
-- =============================================================================

-- 1) Usuário da aplicação
CREATE ROLE evolution_user WITH LOGIN PASSWORD 'ALTERAR_SENHA_FORTE'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- Limite de conexões para não competir com os ABX (ajuste se necessário)
ALTER ROLE evolution_user CONNECTION LIMIT 50;

-- 2) Database dedicado
CREATE DATABASE evolution
  OWNER evolution_user
  ENCODING 'UTF8'
  TEMPLATE template0;

-- Ninguém além do dono conecta neste database
REVOKE ALL ON DATABASE evolution FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE evolution TO evolution_user;

-- 3) Schema usado pela aplicação (?schema=evolution_api na URI)
\connect evolution
CREATE SCHEMA IF NOT EXISTS evolution_api AUTHORIZATION evolution_user;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO evolution_user;

-- =============================================================================
-- Liberação de acesso (pg_hba.conf) - fazer no servidor do Postgres:
--
--   # Evolution API (servidor Docker)
--   host  evolution  evolution_user  IP_DO_SERVIDOR_DOCKER/32  scram-sha-256
--
-- Se o Postgres estiver no MESMO host do Docker, libere a rede das bridges:
--   host  evolution  evolution_user  172.16.0.0/12             scram-sha-256
-- e confira em postgresql.conf se listen_addresses inclui essa interface.
--
-- Depois: SELECT pg_reload_conf();
-- =============================================================================
