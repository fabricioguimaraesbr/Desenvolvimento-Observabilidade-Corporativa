#!/usr/bin/env bash
# =============================================================================
# Prepara um servidor para a stack de monitoramento.
# Rode como root, na raiz do repositório, em cada um dos 3 servidores:
#   sudo ./scripts/preparar-servidor.sh
#
# - cria ${DOCKER_DATA}/<container> (dados) com o dono que cada imagem usa;
# - cria ${MONITORING_DATA}/<container>/ e copia os modelos de variáveis
#   (monitoring-data/*/*.env.example) SEM sobrescrever arquivos que já existem;
# - avisa o que ainda está com valor de exemplo (ALTERAR_, DBxxx, SRVxxx).
# Pode ser rodado de novo sem perder nada.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $EUID -ne 0 ]]; then
  echo "Rode como root (sudo), para criar /u e ajustar os donos das pastas." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Criado .env a partir de .env.example. Ajuste NODE_NAME, NODE_IP e demais valores deste servidor."
fi

# Lê só os caminhos do .env (sem executar o arquivo)
env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
DOCKER_DATA=$(env_value DOCKER_DATA); DOCKER_DATA=${DOCKER_DATA:-/u/docker-data}
MONITORING_DATA=$(env_value MONITORING_DATA); MONITORING_DATA=${MONITORING_DATA:-/u/monitoring-data}

# Usuários das imagens: Zabbix 1997, Grafana 472, Catálogo 10001
ZBX=1997:0
GRAFANA=472:0
CATALOGO=10001:0

mkdata() {  # mkdata <dono> <pasta relativa>...
  local owner=$1; shift
  for d in "$@"; do
    mkdir -p "$DOCKER_DATA/$d"
    chown "$owner" "$DOCKER_DATA/$d"
    chmod 770 "$DOCKER_DATA/$d"
  done
}

echo "== Dados em $DOCKER_DATA"
for c in zabbix-server zabbix-proxy; do
  mkdata "$ZBX" "$c" "$c"/externalscripts "$c"/modules "$c"/enc "$c"/ssh_keys "$c"/mibs \
    "$c"/ssl "$c"/ssl/certs "$c"/ssl/keys "$c"/ssl/ssl_ca
done
mkdata "$ZBX" zabbix-server/alertscripts zabbix-server/export zabbix-proxy/db_data
mkdata "$ZBX" zabbix-web zabbix-web/ssl zabbix-web/modules
mkdata "$GRAFANA" grafana
mkdata "$CATALOGO" catalogo

echo "== Variáveis em $MONITORING_DATA"
for tpl in monitoring-data/*/*.example; do
  c=$(basename "$(dirname "$tpl")")
  dest="$MONITORING_DATA/$c/$(basename "$tpl" .example)"
  mkdir -p "$MONITORING_DATA/$c"
  chmod 750 "$MONITORING_DATA/$c"
  if [[ -e "$dest" ]]; then
    echo "   mantido   $dest"
  else
    cp "$tpl" "$dest"
    chmod 640 "$dest"
    echo "   criado    $dest"
  fi
done
# O catálogo lê rules.yaml com o usuário do container
chown "$CATALOGO" "$MONITORING_DATA/catalogo/rules.yaml"

echo "== Valores de exemplo que ainda precisam ser trocados"
pending=$(grep -RInE "ALTERAR_|DBxxx|SRVxxx|10\.0\.0\.1[123]" .env "$MONITORING_DATA" 2>/dev/null || true)
if [[ -n "$pending" ]]; then
  echo "$pending" | sed 's/^/   /'
else
  echo "   nenhum"
fi

echo
echo "Pronto. Próximos passos (README): conferir os arquivos acima e, só no servidor 1 na primeira vez,"
echo "rodar os jobs de inicialização do banco antes do 'docker compose up -d --build'."
