# Monitoramento Corporativo

Stack de monitoramento em Docker: **Zabbix 8.0 (trunk) em alta disponibilidade** em 3 servidores, com proxy, Java gateway, relatórios, MCP para agentes de IA, browser monitoring (Selenium), Grafana, Portainer agent e o [Catálogo de Monitoramento](catalogo/README.md).

Branch `HML-Corp`: ambiente de homologação corporativo.

## Arquitetura

```
                       zabbix.empresa.com.br / grafana.empresa.com.br
                                         │
                                ┌────────┴────────┐
                                │  F5 corporativo │  health check: GET /ping
                                └────────┬────────┘
             ┌───────────────────────────┼───────────────────────────┐
     ┌───────┴────────┐          ┌───────┴────────┐          ┌───────┴────────┐
     │   SRVxxx01     │          │   SRVxxx02     │          │   SRVxxx03     │
     │ zabbix-server ●│◀── HA ──▶│ zabbix-server ○│◀── HA ──▶│ zabbix-server ○│   ● ativo  ○ standby
     │ zabbix-web     │          │ zabbix-web     │          │ zabbix-web     │
     │ zabbix-proxy   │          │ zabbix-proxy   │          │ zabbix-proxy   │   proxy group (3 proxies)
     │ java-gateway   │          │ java-gateway   │          │ java-gateway   │
     │ web-service    │          │ web-service    │          │ web-service    │
     │ mcp-server     │          │ mcp-server     │          │ mcp-server     │
     │ selenium       │          │ selenium       │          │ selenium       │
     │ grafana        │          │ grafana        │          │ grafana        │
     │ portainer-agent│          │ portainer-agent│          │ portainer-agent│
     │ catalogo       │          │ catalogo       │          │ catalogo       │
     └───────┬────────┘          └───────┬────────┘          └───────┬────────┘
             └───────────────────────────┼───────────────────────────┘
                                ┌────────┴────────┐
                                │      DBxxx      │  PostgreSQL 17 + TimescaleDB (zabbix, grafana)
                                │                 │  ClickHouse (APM: traces, métricas, logs OTel)
                                └─────────────────┘
```

- **Uma stack por servidor.** O `docker-compose.yml` da raiz é o mesmo nos 3. O que muda entre eles fica só no `.env` do servidor: `NODE_NAME`, `NODE_IP` e horário de coleta do catálogo.
- **HA do Zabbix server:** os 3 nós usam o mesmo banco; um fica ativo e os outros dois em standby. Se o ativo cai, um standby assume em cerca de 1 minuto. O frontend descobre sozinho o nó ativo pelo banco, por isso o web **não** tem `ZBX_SERVER_HOST`.
- **Proxies:** um por servidor (`proxy-SRVxxx01`..03), cada um conhecendo os 3 nós do HA. No frontend eles formam um **proxy group**, que redistribui os hosts se um proxy cair. Os proxies também recebem **APM** (OpenTelemetry, OTLP gRPC na porta 4317) e gravam no ClickHouse.
- **Banco:** fica no **DBxxx**, que já existe. Este repositório só traz os scripts para o DBA, em `db/`.
- **Grafana:** usa banco compartilhado no PostgreSQL, então os 3 mostram os mesmos dashboards atrás do F5. O alerting roda em HA entre os 3 (porta 9094).

### Imagens

| Container | Imagem | Portas no servidor |
|---|---|---|
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-trunk` | 10051 |
| `zabbix-web` | `zabbix/zabbix-web-nginx-pgsql:alpine-trunk` | 80, 443 |
| `zabbix-proxy` | `zabbix/zabbix-proxy-sqlite3:alpine-trunk` | 10061 (trapper), 4317 (APM/OTLP) |
| `zabbix-java-gateway` | `zabbix/zabbix-java-gateway:alpine-trunk` | só rede interna |
| `zabbix-web-service` | `zabbix/zabbix-web-service:alpine-trunk` | só rede interna |
| `zabbix-mcp-server` | `zabbix/zabbix-mcp-server:alpine-trunk` | 8444 |
| `selenium` | `selenium/standalone-chrome:latest` | só rede interna |
| `grafana` | `grafana/grafana:13.2.4` | 3000, 9094 (HA do alerting) |
| `portainer-agent` | `portainer/agent:latest` | 9001 |
| `catalogo` | build de `catalogo/` | 8088 (diagnóstico; o acesso normal é `/catalogo/` no web) |

> **Sobre o trunk:** `alpine-trunk` é o Zabbix **8.0 em desenvolvimento** (hoje 8.0.0rc3). A imagem muda a cada build. Para fixar uma versão, troque `ZABBIX_TAG` no `.env`, por exemplo para a tag 8.0 estável quando sair.

## Diretórios

| Onde | O quê |
|---|---|
| Raiz do repositório | `docker-compose.yml` e o `.env` do servidor |
| `/u/docker-data/<container>` | Dados persistentes de cada container (SQLite do proxy, Grafana, catálogo, certificados, scripts, módulos) |
| `/u/monitoring-data/<container>/<container>.env` | Variáveis de cada container (modelos em `monitoring-data/`) |

```
docker-compose.yml          stack de um servidor
.env.example                variáveis do servidor (NODE_NAME, NODE_IP, portas, caminhos)
monitoring-data/            modelos das variáveis de cada container
config/
  zabbix-web/               /catalogo/ no nginx do Zabbix web
  zabbix-web-service/       perfil seccomp do Chrome (relatórios PDF)
  grafana/provisioning/     plugin e datasource do Zabbix
db/                         scripts para o DBA do DBxxx
scripts/
  preparar-servidor.sh      cria /u/docker-data e /u/monitoring-data
  validar.sh                checagens depois da subida
catalogo/                   Catálogo de Monitoramento (código, testes, README próprio)
```

## Passo a passo

### 1. Banco no DBxxx (DBA)

Troque as senhas e os IPs dos 3 servidores nos comandos e arquivos abaixo.

```bash
# PostgreSQL 17 + TimescaleDB: usuário/banco do Zabbix e extensão timescaledb
psql -h DBxxx -U postgres -d postgres -v senha=SENHA_ZABBIX -f db/01-zabbix-postgresql.sql
# Banco do Grafana
psql -h DBxxx -U postgres -d postgres -v senha=SENHA_GRAFANA -f db/02-grafana-postgresql.sql
# ClickHouse: banco e usuário do Zabbix (edite senha e IPs no arquivo antes)
clickhouse-client -h DBxxx --user default --password SENHA_ADMIN --multiquery < db/04-clickhouse.sql
```

Libere os 3 servidores no `pg_hba.conf` (modelo em `db/pg_hba.conf.example`) e rode `SELECT pg_reload_conf();`. O ClickHouse precisa aceitar conexões HTTP na porta 8123 vindas dos 3 servidores.

O usuário somente leitura do catálogo (`db/03-catalogo-usuario-somente-leitura.sql`) é criado **depois** do schema do Zabbix (passo 4), porque concede acesso às tabelas.

### 2. Preparar cada servidor

Em cada um dos 3 servidores, com o repositório clonado:

```bash
cp .env.example .env              # ajuste NODE_NAME, NODE_IP, ZBX_HA_NODES, GRAFANA_HA_PEERS, CATALOGO_COLLECT_AT
sudo ./scripts/preparar-servidor.sh
```

O script cria `/u/docker-data/*` com o dono certo de cada imagem (Zabbix uid 1997, Grafana 472, Catálogo 10001). Também copia os modelos para `/u/monitoring-data/*/*.env`, sem sobrescrever arquivos que já existem. No fim, lista o que ainda está com valor de exemplo (`ALTERAR_`, `DBxxx`, `SRVxxx`, IPs `10.0.0.1x`).

Edite `/u/monitoring-data/*/*.env` com os valores reais. Os arquivos são **iguais nos 3 servidores**: o que é de cada nó vem do `.env` da raiz. Atenção a dois valores:
- `GF_SECURITY_SECRET_KEY` do Grafana precisa ser **o mesmo nos 3**.
- `ZABBIX_API_TOKEN` do Grafana só existe depois do passo 5. Até lá, o datasource do Zabbix fica sem autenticar.

**HTTPS no próprio Zabbix web (opcional):** coloque `ssl.crt`, `ssl.key` e `dhparam.pem` em `/u/docker-data/zabbix-web/ssl/`. Se o F5 termina o TLS, pode deixar só HTTP.

### 3. Inicializar o schema (uma vez, só no servidor 1)

```bash
docker compose --profile init run --rm zabbix-db-init         # tabelas + hypertables TimescaleDB no PostgreSQL
docker compose --profile init run --rm zabbix-telemetry-init  # tabelas de APM no ClickHouse
```

Os jobs ficam no profile `init` e **não** sobem com `docker compose up`. Assim os 3 servidores nunca disputam a criação do schema.

### 4. Subir

```bash
# servidor 1 primeiro; depois 2 e 3
docker compose up -d --build
```

Depois do servidor 1 no ar, crie o usuário do catálogo no DBxxx, **conectado no banco do Zabbix**:

```bash
psql -h DBxxx -U postgres -d zabbix -v senha=SENHA_CATALOGO -f db/03-catalogo-usuario-somente-leitura.sql
```

### 5. Configurar no frontend do Zabbix

1. Troque a senha do `Admin`.
2. **Proxies:** em *Administração → Proxies*, crie os proxies `proxy-SRVxxx01`, `proxy-SRVxxx02` e `proxy-SRVxxx03` (modo ativo) e um **proxy group** com os três (*Administração → Proxy groups*, mínimo online = 1). Monitore os hosts pelo proxy group.
3. **Token do Grafana:** crie um usuário de serviço com papel somente leitura e um token de API para ele. Coloque o token em `ZABBIX_API_TOKEN` no `grafana.env` dos 3 servidores e rode `docker compose up -d grafana`.
4. **Relatórios:** em *Administração → Geral → Outros*, ajuste a *URL do frontend* para `https://zabbix.empresa.com.br/`. O web service usa essa URL para gerar os PDFs.

### 6. Balanceador (F5)

| Serviço | Pool | Health check |
|---|---|---|
| `zabbix.empresa.com.br` | 3 servidores, porta 80 (ou 443) | `GET /ping` → 200 |
| `grafana.empresa.com.br` | 3 servidores, porta 3000 | `GET /api/health` → 200 |
| MCP (opcional) | 3 servidores, porta 8444 | TCP |

Sem afinidade de sessão para o Zabbix web: as sessões ficam no banco. Para o Zabbix ver o IP real dos usuários, ajuste `WEB_REAL_IP_FROM` e `WEB_REAL_IP_HEADER` no `zabbix-web.env`. O `/catalogo/` sai pelo mesmo endereço do Zabbix.

Os **agentes** e as **aplicações com OpenTelemetry** não passam pelo F5:
- **Agentes ativos:** `ServerActive=10.0.0.11:10051;10.0.0.12:10051;10.0.0.13:10051`, ou o proxy group.
- **APM:** apontam para a porta 4317 de qualquer proxy.

### 7. Validar

Em cada servidor:

```bash
./scripts/validar.sh
ZABBIX_API_TOKEN=... ./scripts/validar.sh      # inclui o teste do MCP
```

O script confere:
- se os 10 containers estão de pé e o estado do HA (`zabbix_server -R ha_status`);
- `/ping` do web, `/catalogo/`, Grafana, Portainer agent, Selenium, Java gateway e web service;
- erros recentes nos logs.

## Roteiro de testes de homologação

| # | Teste | Como | Esperado |
|---|---|---|---|
| 1 | HA | `docker exec zabbix-server zabbix_server -R ha_status` em qualquer servidor | 3 nós: 1 `active`, 2 `standby` |
| 2 | Failover | `docker stop zabbix-server` no nó ativo; depois `ha_status` em outro | Um standby vira `active` em até ~1 min; o frontend segue funcionando. Depois, `docker start zabbix-server` |
| 3 | Frontend em cada nó | `curl -I http://<IP>/` nos 3 | 200 nos 3 |
| 4 | Proxy group | *Administração → Proxies* | 3 proxies online; ao parar um (`docker stop zabbix-proxy`), os hosts dele passam para outro |
| 5 | Catálogo | `https://zabbix.empresa.com.br/catalogo/` | Lista as aplicações; `/catalogo` e `/catálogo` redirecionam |
| 6 | JMX | Host com interface JMX e template *Generic Java JMX* | Itens JMX coletando |
| 7 | Relatório | *Relatórios → Relatórios agendados → Testar* | PDF gerado e enviado |
| 8 | Browser item | Item do tipo *Browser* (ex.: template *Website by Browser*) | Item coletando via Selenium |
| 9 | MCP | `validar.sh` com `ZABBIX_API_TOKEN` | `tools/list` responde |
| 10 | Grafana | `https://grafana.empresa.com.br` → *Connections → Data sources → Zabbix → Test* | Datasource OK; mesmo dashboard visto pelos 3 nós |
| 11 | APM | App com OpenTelemetry exportando para `<IP do proxy>:4317` | Traces aparecem no Zabbix |
| 12 | Portainer | Cadastrar `<IP>:9001` como Agent no Portainer server | 3 ambientes conectados |

## Operação

```bash
docker compose ps
docker compose logs -f zabbix-server
docker compose pull && docker compose up -d       # atualizar imagens (um servidor por vez)
docker compose down                               # parar a stack deste servidor (os dados em /u ficam)
```

Para atualizar o trunk, faça **um servidor por vez**. Comece pelos standby e deixe o ativo por último. Quando o schema muda entre builds, o primeiro server a subir aplica o upgrade no banco.

## Pendências para o ambiente real

- Trocar os nomes fictícios: `DBxxx`, `SRVxxx01..03`, IPs `10.0.0.11..13`, `empresa.com.br`.
- Definir todas as senhas marcadas com `ALTERAR_`.
- Configurar os pools no F5.
- Opcional: PSK entre proxies e server (`ZBX_TLS*` no `zabbix-proxy.env`), TLS com o banco (`ZBX_DBTLS*`) e `AGENT_SECRET` do Portainer.
