# Evolution API – modelo Docker Compose (ambiente corporativo)

Estrutura pronta para implantar a [Evolution API](https://github.com/EvolutionAPI/evolution-api) v2 no ambiente corporativo. Na implantação você só precisa preencher o arquivo `.env`.

```
evolution-api/
├── docker-compose.yml           # API + Redis (+ Postgres e Manager opcionais)
├── .env.example                 # todas as variáveis, comentadas
├── sql/
│   └── 01-create-evolution-db.sql  # usuário/database no Postgres corporativo
├── scripts/
│   └── backup.sh                # dump do banco + volume de instâncias
└── .gitignore
```

## Arquitetura

| Serviço    | Imagem                                   | Padrão              | Porta no host |
|------------|------------------------------------------|---------------------|---------------|
| `api`      | `evoapicloud/evolution-api:v2.3.7`       | sempre              | `8081` (`API_HOST_PORT`) |
| `redis`    | `redis:7-alpine`                         | sempre              | nenhuma (rede interna) |
| `postgres` | `postgres:15-alpine`                     | `--profile local-db`| nenhuma (rede interna) |
| `manager`  | `evoapicloud/evolution-manager`          | `--profile manager` | `3001` (`MANAGER_HOST_PORT`) |

- **Banco de dados:** por padrão é usado o **PostgreSQL corporativo** que já existe, em um database e com um usuário próprios. O Postgres em container serve só para testes.
- **Porta:** a 8080 do host já está ocupada pelos ABX, então a API fica publicada na **8081**. Dentro do container ela continua na 8080.

## Pré-requisitos

- Docker Engine 24+ e Docker Compose v2.20+ (`docker compose version`)
- Acesso de rede do servidor Docker ao Postgres corporativo (porta 5432)
- Saída para a internet (WhatsApp) direta ou por proxy (`PROXY_*` no `.env`)

## Passo a passo

### 1. Preparar o Postgres corporativo (DBA)

Edite a senha em `sql/01-create-evolution-db.sql` e execute:

```bash
psql -h HOST_POSTGRES -U postgres -f sql/01-create-evolution-db.sql
```

O script cria:
- o usuário `evolution_user` com limite de 50 conexões;
- o database `evolution`, isolado dos dados dos ABX;
- o schema `evolution_api`, onde a Evolution cria as tabelas sozinha na primeira inicialização.

> **Não use o database nem o usuário dos ABX.** A Evolution executa migrations (Prisma) que criam e alteram tabelas. Mantenha tudo isolado.

Depois, libere o acesso no `pg_hba.conf` e recarregue:

```
host  evolution  evolution_user  IP_DO_SERVIDOR_DOCKER/32  scram-sha-256
```

```sql
SELECT pg_reload_conf();
```

Pontos de atenção:
- **Versão:** PostgreSQL 13 ou superior.
- **`max_connections`:** confira se há folga para mais cerca de 50 conexões, além das usadas pelos ABX.
- **Postgres no mesmo servidor do Docker:** use `host.docker.internal` como host na URI. Libere a rede das bridges Docker (`172.16.0.0/12`) no `pg_hba.conf` e garanta que `listen_addresses` inclua essa interface (não só `localhost`).
- **SSL obrigatório:** acrescente `&sslmode=require` na URI.

### 2. Configurar o `.env`

```bash
cp .env.example .env
openssl rand -hex 32   # use como AUTHENTICATION_API_KEY
```

Variáveis **obrigatórias** (procure por `ALTERAR_`):

| Variável | Exemplo |
|---|---|
| `SERVER_URL` | `https://evolution.suaempresa.com.br` ou `http://10.0.0.50:8081` |
| `AUTHENTICATION_API_KEY` | saída do `openssl rand -hex 32` |
| `DATABASE_CONNECTION_URI` | `postgresql://evolution_user:SENHA@pg.suaempresa.local:5432/evolution?schema=evolution_api` |

Opcionais comuns: `API_HOST_PORT`, `API_BIND_IP`, `CORS_ORIGIN`, `PROXY_*`, `WEBHOOK_GLOBAL_*`, `S3_*`.

> Senhas com `@ : / # ? %` precisam ser codificadas na URI (ex.: `@` → `%40`).

### 3. Validar e subir

```bash
docker compose config --quiet && echo OK
```

```bash
docker compose up -d
```

```bash
docker compose ps
```

```bash
docker compose logs -f api
```

Teste:

```bash
curl -s http://localhost:8081/
```

A resposta deve ter `"status":200` e a versão da API. A documentação interativa fica em `SERVER_URL/docs` e o painel em `SERVER_URL/manager`.

### Subir com Postgres local (testes/homologação)

No `.env`, use:

```
DATABASE_CONNECTION_URI=postgresql://evolution_user:troque_esta_senha@postgres:5432/evolution?schema=evolution_api
```

```bash
docker compose --profile local-db up -d
```

### Evolution Manager (opcional)

```bash
docker compose --profile manager up -d
```

Acesse `http://SERVIDOR:3001`, informe a `SERVER_URL` e a API key.

## Trocar a porta

Altere `API_HOST_PORT` no `.env` e rode `docker compose up -d`. Atualize também `SERVER_URL` se ela incluir a porta. **Não altere `SERVER_PORT`**: ela é a porta interna do container e fica sempre em 8080.

## Proxy reverso (Nginx corporativo)

Exemplo com HTTPS e WebSocket:

```nginx
server {
    listen 443 ssl;
    server_name evolution.suaempresa.com.br;

    ssl_certificate     /etc/nginx/certs/evolution.crt;
    ssl_certificate_key /etc/nginx/certs/evolution.key;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

Com o proxy no mesmo host, use `API_BIND_IP=127.0.0.1` para a API não ficar exposta direto.

## Backup

```bash
./scripts/backup.sh
```

O script gera `backups/AAAAMMDD-HHMMSS/` com:
- `evolution.dump`: o banco, no formato custom do `pg_dump`;
- `evolution_instances.tar.gz`: as sessões do WhatsApp. Sem esse arquivo, os números precisam ler o QR code de novo.

Se o backup do Postgres corporativo já é feito pela sua rotina de DBA, basta incluir o database `evolution` nela e usar o script só para o volume. O dump roda com `--network host`, então a URI precisa apontar para um host que o servidor resolva (não `host.docker.internal`).

Restaurar o banco:

```bash
pg_restore -h HOST -U evolution_user -d evolution --clean --no-owner evolution.dump
```

## Atualizar a versão

1. Faça o backup.
2. Altere `EVOLUTION_IMAGE_TAG` no `.env` (veja as [tags](https://hub.docker.com/r/evoapicloud/evolution-api/tags)).
3. Rode `docker compose pull api && docker compose up -d api`. As migrations rodam automaticamente na inicialização.

## Troubleshooting

| Sintoma | Causa provável |
|---|---|
| `Defina ... no .env` ao subir | variável obrigatória vazia |
| `port is already allocated` | `API_HOST_PORT` em uso: escolha outra |
| `P1001: Can't reach database server` | host/porta errados, firewall, ou `listen_addresses` |
| `no pg_hba.conf entry for host` | liberar o IP do servidor Docker no `pg_hba.conf` |
| `permission denied for schema` | rodar novamente a parte de schema/grants do SQL |
| QR code não aparece / instância cai | saída para internet bloqueada: configure `PROXY_*` |
| Webhooks com URL errada | `SERVER_URL` não corresponde ao endereço externo |
