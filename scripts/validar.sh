#!/usr/bin/env bash
# =============================================================================
# Checagens depois de subir a stack em um servidor:
#   ./scripts/validar.sh
# Para testar também o MCP, passe um token de API do Zabbix:
#   ZABBIX_API_TOKEN=... ./scripts/validar.sh
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
WEB_HTTP_PORT=$(env_value WEB_HTTP_PORT); WEB_HTTP_PORT=${WEB_HTTP_PORT:-80}
MCP_PORT=$(env_value MCP_PORT); MCP_PORT=${MCP_PORT:-8444}
GRAFANA_PORT=$(env_value GRAFANA_PORT); GRAFANA_PORT=${GRAFANA_PORT:-3000}
PORTAINER_AGENT_PORT=$(env_value PORTAINER_AGENT_PORT); PORTAINER_AGENT_PORT=${PORTAINER_AGENT_PORT:-9001}

falhas=0
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFALHA\033[0m %s\n' "$1"; falhas=$((falhas + 1)); }
check() {  # check <descrição> <comando...>
  local desc=$1; shift
  if "$@" >/dev/null 2>&1; then ok "$desc"; else fail "$desc"; fi
}

echo "== Containers"
for c in zabbix-server zabbix-web zabbix-proxy zabbix-java-gateway zabbix-web-service \
         zabbix-mcp-server selenium grafana catalogo; do
  state=$(docker inspect -f '{{.State.Status}}{{if .State.Health}}/{{.State.Health.Status}}{{end}}' "$c" 2>/dev/null)
  case $state in
    running|running/healthy) ok "$c ($state)" ;;
    *) fail "$c (${state:-não existe})" ;;
  esac
done

echo "== Zabbix server em HA"
if ha=$(docker exec zabbix-server zabbix_server -R ha_status 2>&1); then
  echo "$ha" | sed 's/^/        /'
  if grep -qi "active" <<<"$ha"; then ok "há um nó ativo no cluster"; else fail "nenhum nó ativo listado"; fi
else
  fail "zabbix_server -R ha_status: $ha"
fi

echo "== Serviços"
check "Zabbix web responde em :$WEB_HTTP_PORT/ping" curl -fsS "http://127.0.0.1:$WEB_HTTP_PORT/ping"
check "Catálogo responde em :$WEB_HTTP_PORT/catalogo/api/health" curl -fsS "http://127.0.0.1:$WEB_HTTP_PORT/catalogo/api/health"
check "Grafana saudável em :$GRAFANA_PORT/api/health" curl -fsS "http://127.0.0.1:$GRAFANA_PORT/api/health"
check "Portainer agent (instalado fora da stack) escuta em :$PORTAINER_AGENT_PORT" bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORTAINER_AGENT_PORT"
check "Selenium pronto (status do grid)" docker exec selenium curl -fsS http://localhost:4444/status
check "Java gateway escuta em 10052 (rede interna)" docker exec zabbix-server sh -c "nc -z zabbix-java-gateway 10052"
check "Web service escuta em 10053 (rede interna)" docker exec zabbix-server sh -c "nc -z zabbix-web-service 10053"

if [[ -n "${ZABBIX_API_TOKEN:-}" ]]; then
  check "MCP server lista ferramentas em :$MCP_PORT/mcp" bash -c "curl -fsS http://127.0.0.1:$MCP_PORT/mcp \
    -H 'Authorization: Bearer $ZABBIX_API_TOKEN' -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' | grep -q '\"tools\"'"
else
  echo "  --    MCP não testado (defina ZABBIX_API_TOKEN para testar)"
fi

echo "== Erros recentes nos logs (últimos 15 min)"
for c in zabbix-server zabbix-proxy zabbix-web; do
  n=$(docker logs --since 15m "$c" 2>&1 | grep -ciE "cannot|error|failed" || true)
  if [[ $n -eq 0 ]]; then ok "$c sem erros"; else echo "  !!    $c: $n linha(s) com erro. Veja: docker logs --since 15m $c"; fi
done

echo
if [[ $falhas -eq 0 ]]; then echo "Tudo certo neste servidor."; else echo "$falhas checagem(ns) falharam."; fi
exit $(( falhas > 0 ))
