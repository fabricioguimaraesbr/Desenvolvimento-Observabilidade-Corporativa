#!/usr/bin/env bash
# =============================================================================
# Backup da Evolution API
#   - Dump do database (lido de DATABASE_CONNECTION_URI no .env)
#   - Volume de instâncias (sessões do WhatsApp)
#
# Uso (a partir da pasta evolution-api/):  ./scripts/backup.sh
# Saída: backups/AAAAMMDD-HHMMSS/
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Arquivo .env não encontrado em $(pwd)" >&2
  exit 1
fi

DB_URI="$(grep -E '^DATABASE_CONNECTION_URI=' .env | head -n1 | cut -d= -f2- | tr -d "'\"")"
# pg_dump não aceita o parâmetro ?schema= do Prisma
DB_URI_PG="$(echo "$DB_URI" | sed -E 's/([?&])schema=[^&]*&?/\1/; s/[?&]$//')"

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="backups/${STAMP}"
mkdir -p "$DEST"

PROJECT="$(docker compose config --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' 2>/dev/null || echo evolution)"

echo ">> Dump do database..."
# Usa a imagem do Postgres para não depender de pg_dump instalado no host.
# --network host permite alcançar o Postgres corporativo como o host enxerga.
docker run --rm --network host \
  -v "$(pwd)/${DEST}:/backup" \
  "postgres:${POSTGRES_IMAGE_TAG:-15-alpine}" \
  pg_dump "$DB_URI_PG" --format=custom --no-owner --file=/backup/evolution.dump

echo ">> Backup do volume de instâncias..."
docker run --rm \
  -v "${PROJECT}_evolution_instances:/data:ro" \
  -v "$(pwd)/${DEST}:/backup" \
  alpine:3.20 tar czf /backup/evolution_instances.tar.gz -C /data .

echo ">> Backup concluído em ${DEST}"
ls -lh "$DEST"
