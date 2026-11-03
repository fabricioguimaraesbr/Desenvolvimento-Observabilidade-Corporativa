#!/usr/bin/env bash
# =============================================================================
# Prepara um servidor para a stack de monitoramento.
# Rode como root, na raiz do repositório, em cada um dos 3 servidores:
#   sudo ./scripts/preparar-servidor.sh
#
# - cria .env a partir de .env.example, se ainda não existir;
# - cria monitoring-data/<container>/<container>.env a partir dos modelos
#   (*.example), SEM sobrescrever arquivos que já existem;
# - cria data/<container> (dados persistentes) com o dono que cada imagem usa;
# - avisa o que ainda está com valor de exemplo (ALTERAR_, DBxxx, SRVxxx).
# Pode ser rodado de novo sem perder nada.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $EUID -ne 0 ]]; then
  echo "Rode como root (sudo), para ajustar os donos das pastas em data/." >&2
  exit 1
fi

# Usuários das imagens: Zabbix 1997, Grafana 472, Catálogo 10001
ZBX=1997:0
GRAFANA=472:0
CATALOGO=10001:0

copy_template() {  # copy_template <modelo .example>
  local dest=${1%.example}
  if [[ -e "$dest" ]]; then
    echo "   mantido   $dest"
  else
    cp "$1" "$dest"
    chmod 640 "$dest"
    echo "   criado    $dest"
  fi
}

echo "== Arquivos de variáveis"
copy_template .env.example
for tpl in monitoring-data/*/*.example; do
  copy_template "$tpl"
done
# O catálogo lê rules.yaml com o usuário do container
chown "$CATALOGO" monitoring-data/catalogo/rules.yaml

mkdata() {  # mkdata <dono> <pasta relativa>...
  local owner=$1; shift
  for d in "$@"; do
    mkdir -p "data/$d"
    chown "$owner" "data/$d"
    chmod 770 "data/$d"
  done
}

echo "== Dados em data/"
for c in zabbix-server zabbix-proxy; do
  mkdata "$ZBX" "$c" "$c"/externalscripts "$c"/modules "$c"/enc "$c"/ssh_keys "$c"/mibs \
    "$c"/ssl "$c"/ssl/certs "$c"/ssl/keys "$c"/ssl/ssl_ca
done
mkdata "$ZBX" zabbix-server/alertscripts zabbix-server/export zabbix-proxy/db_data
mkdata "$ZBX" zabbix-web zabbix-web/ssl zabbix-web/modules
mkdata "$GRAFANA" grafana
mkdata "$CATALOGO" catalogo

echo "== Valores de exemplo que ainda precisam ser trocados"
pending=$(grep -InE "ALTERAR_|DBxxx|SRVxxx|10\.0\.0\.1[123]" .env monitoring-data/*/*.env 2>/dev/null || true)
if [[ -n "$pending" ]]; then
  echo "$pending" | sed 's/^/   /'
else
  echo "   nenhum"
fi

echo
echo "Pronto. Depois de trocar os valores acima: docker compose up -d --build"
