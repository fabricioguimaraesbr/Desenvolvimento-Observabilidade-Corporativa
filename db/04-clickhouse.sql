-- =============================================================================
-- ClickHouse no DBxxx: banco e usuário do Zabbix para APM (OpenTelemetry)
-- Troque ALTERAR_senha_do_clickhouse e os IPs, depois rode:
--   clickhouse-client -h DBxxx --user default --password <senha-admin> --multiquery < db/04-clickhouse.sql
-- As tabelas (traces, métricas, logs) são criadas pelo job zabbix-telemetry-init
-- da stack, rodado uma vez no servidor 1 (ver README).
-- =============================================================================
CREATE DATABASE IF NOT EXISTS zabbix;

CREATE USER IF NOT EXISTS zabbix IDENTIFIED WITH sha256_password BY 'ALTERAR_senha_do_clickhouse'
  HOST IP '10.0.0.11', IP '10.0.0.12', IP '10.0.0.13';   -- troque pelos IPs reais dos 3 servidores

GRANT ALL ON zabbix.* TO zabbix;
