# Monitoramento Corporativo

Stack de monitoramento em Docker: **Zabbix 8.0 (trunk) em alta disponibilidade** em 3 servidores, com proxy, Java gateway, relatórios, MCP para agentes de IA, browser monitoring (Selenium), Grafana e o [Catálogo de Monitoramento](catalogo/README.md).

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
     │ catalogo       │          │ catalogo       │          │ catalogo       │
     └───────┬────────┘          └───────┬────────┘          └───────┬────────┘
             └───────────────────────────┼───────────────────────────┘
                                ┌────────┴────────┐
                                │      DBxxx      │  PostgreSQL do Zabbix 8.0 (zabbix, grafana)
                                │                 │  ClickHouse (APM: traces, métricas, logs OTel)
                                └─────────────────┘
```

- **Uma stack por servidor.** O `docker-compose.yml` da raiz é o mesmo nos 3. Cada servidor tem um clone do repositório e roda `docker compose` nele; o que muda entre os 3 fica só no `.env` de cada um: `NODE_NAME`, `NODE_IP` e horário de coleta do catálogo.
- **HA do Zabbix server:** os 3 nós usam o mesmo banco; um fica ativo e os outros dois em standby. Se o ativo cai, um standby assume em cerca de 1 minuto. O frontend descobre sozinho o nó ativo pelo banco, por isso o web **não** tem `ZBX_SERVER_HOST`.
- **Proxies:** um por servidor (`proxy-SRVxxx01`..03), cada um conhecendo os 3 nós do HA. No frontend eles formam um **proxy group**, que redistribui os hosts se um proxy cair. Os proxies também recebem **APM** (OpenTelemetry, OTLP gRPC na porta 4317) e gravam no ClickHouse.
- **Banco:** PostgreSQL e ClickHouse ficam no **DBxxx** e já existem, com o schema do Zabbix 8.0 criado. A stack só aponta para eles pelas variáveis; não cria banco, usuário nem tabela.
- **Grafana:** usa banco compartilhado no PostgreSQL, então os 3 mostram os mesmos dashboards atrás do F5. O alerting roda em HA entre os 3 (porta 9094).

### Imagens

| Container | Imagem | Portas no servidor |
|---|---|---|
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-trunk` | 10051 |
| `zabbix-web` | build local de `config/zabbix-web/` (`zabbix/zabbix-web-nginx-pgsql:alpine-trunk` + `/catalogo/`) | 80 |
| `zabbix-proxy` | `zabbix/zabbix-proxy-sqlite3:alpine-trunk` | 10061 (trapper), 4317 (APM/OTLP) |
| `zabbix-java-gateway` | `zabbix/zabbix-java-gateway:alpine-trunk` | só rede interna |
| `zabbix-web-service` | `zabbix/zabbix-web-service:alpine-trunk` | só rede interna |
| `zabbix-mcp-server` | `zabbix/zabbix-mcp-server:alpine-trunk` | 8444 |
| `selenium` | `selenium/standalone-chrome:latest` | só rede interna |
| `grafana` | build local de `config/grafana/` (`grafana/grafana:13.2.4` + plugin, datasource e LDAP) | 3000, 9094 (HA do alerting) |
| `catalogo` | build local de `catalogo/` | 8088 (diagnóstico; o acesso normal é `/catalogo/` no web) |

> **Sobre o trunk:** `alpine-trunk` é o Zabbix **8.0 em desenvolvimento** (hoje 8.0.0rc3). A imagem muda a cada build. Para fixar uma versão, defina `ZABBIX_TAG` nas variáveis da stack, por exemplo para a tag 8.0 estável quando sair.

## Arquivos e diretórios

```
docker-compose.yml          stack de um servidor (igual nos 3)
.env.example                modelo do .env: senhas e valores de cada servidor
monitoring-data/<container>/<container>.env   demais variáveis de cada container (sem senhas)
config/
  zabbix-web/               Dockerfile + nginx com o /catalogo/
  grafana/                  Dockerfile + plugin e datasource do Zabbix + LDAP (ldap.toml, certs/)
  zabbix-web-service/       perfil seccomp do Chrome (relatórios PDF)
scripts/validar.sh          checagens depois da subida
catalogo/                   Catálogo de Monitoramento (código, regras, testes, README próprio)
```

### Onde fica cada variável

| Arquivo | O quê | No Git? |
|---|---|---|
| **`.env`** (raiz) | senhas, token do Grafana e o que muda por servidor (`NODE_NAME`, `NODE_IP`, `CATALOGO_COLLECT_AT`) | **Não**: cada servidor tem o seu, criado a partir do `.env.example` |
| `monitoring-data/*/*.env` | todo o resto: endereço do DBxxx, usuários do banco, desempenho do Zabbix, Grafana e LDAP, MCP, Selenium | Sim, iguais nos 3 |
| `catalogo/config/rules.yaml` | regras do catálogo | Sim |

**Nunca coloque senha nos arquivos do Git.** No `docker-compose.yml`, cada senha vem do `.env` e é obrigatória: se faltar, o `docker compose` para dizendo qual falta. O `.env` está no `.gitignore`, então o `git pull` nunca sobrescreve nem publica o que você preencheu.

O nginx do `/catalogo/` e as configs do Grafana vão dentro de imagens construídas no próprio servidor (`config/zabbix-web/` e `config/grafana/`), junto com o catálogo. Os dados ficam em **volumes nomeados** do Docker (`zabbix-proxy-data`, `grafana-data`, `catalogo-data` e as pastas de scripts do Zabbix), criados com o dono certo, sem precisar preparar pastas.

## Passo a passo

### 1. Pré-requisitos

No **DBxxx** (já existentes; só confira):
- os 3 servidores conseguem conectar no PostgreSQL (5432) e no ClickHouse (HTTP 8123);
- existe um database `grafana` com usuário para o Grafana;
- existe um usuário **somente leitura** no banco do Zabbix para o catálogo.

Nos **3 servidores**: Docker com o plugin `docker compose`, `git` e acesso de saída para baixar as imagens (Docker Hub) e o plugin do Grafana no build.

### 2. Ajustar o que fica no Git

Troque os nomes fictícios em `monitoring-data/*/*.env` (`DBxxx`, `empresa.com.br`, LDAP, redes do MCP) e faça commit. Esses arquivos são **iguais nos 3 servidores**.

### 3. Subir em cada servidor

```bash
git clone -b HML-Corp <url-do-repositório> monitoramento
cd monitoramento
cp .env.example .env      # copie, não renomeie
vi .env                   # preencha
docker compose up -d --build
```

No `.env`, só `NODE_NAME`, `NODE_IP` e `CATALOGO_COLLECT_AT` mudam entre os 3 servidores; o resto é igual. A `GRAFANA_SECRET_KEY` **precisa** ser a mesma nos 3. O `ZABBIX_API_TOKEN` fica vazio até o passo 4. Proteja o arquivo: `chmod 600 .env`.

O primeiro `up` demora mais porque constrói as imagens do Zabbix web, do Grafana e do catálogo.

### 4. Configurar no frontend do Zabbix

1. Troque a senha do `Admin`.
2. **Proxies:** em *Administração → Proxies*, crie os proxies `proxy-SRVxxx01`, `proxy-SRVxxx02` e `proxy-SRVxxx03` (modo ativo) e um **proxy group** com os três (*Administração → Proxy groups*, mínimo online = 1). Monitore os hosts pelo proxy group.
3. **Token do Grafana:** crie um usuário de serviço com papel somente leitura e um token de API para ele. Coloque o token em `ZABBIX_API_TOKEN` no `.env` dos 3 servidores e rode `docker compose up -d grafana`.
4. **Relatórios:** em *Administração → Geral → Outros*, ajuste a *URL do frontend* para `https://zabbix.empresa.com.br/`. O web service usa essa URL para gerar os PDFs.

### 5. Balanceador (F5)

| Serviço | Pool | Health check |
|---|---|---|
| `zabbix.empresa.com.br` | 3 servidores, porta 80 | `GET /ping` → 200 |
| `grafana.empresa.com.br` | 3 servidores, porta 3000 | `GET /api/health` → 200 |
| MCP (opcional) | 3 servidores, porta 8444 | TCP |

Sem afinidade de sessão para o Zabbix web: as sessões ficam no banco. Para o Zabbix ver o IP real dos usuários, ajuste `WEB_REAL_IP_FROM` e `WEB_REAL_IP_HEADER` no `zabbix-web.env`. O `/catalogo/` sai pelo mesmo endereço do Zabbix.

Os **agentes** e as **aplicações com OpenTelemetry** não passam pelo F5:
- **Agentes ativos:** `ServerActive=10.0.0.11:10051;10.0.0.12:10051;10.0.0.13:10051`, ou o proxy group.
- **APM:** apontam para a porta 4317 de qualquer proxy.

### 6. LDAP no Grafana

O Grafana autentica no AD pelo `config/grafana/ldap.toml`, que vai dentro da imagem e lê tudo de variáveis:

| Onde | Variável | O quê |
|---|---|---|
| `grafana.env` (Git) | `LDAP_HOST`, `LDAP_PORT`, `LDAP_USE_SSL`, `LDAP_START_TLS` | controladores de domínio e LDAPS (636) ou LDAP (389) |
| `grafana.env` (Git) | `LDAP_BIND_DN` | conta de serviço que consulta o AD |
| `grafana.env` (Git) | `LDAP_SEARCH_BASE_DN`, `LDAP_SEARCH_FILTER` | onde procurar os usuários (padrão AD: `sAMAccountName`) |
| `grafana.env` (Git) | `LDAP_GROUP_ADMIN_DN`, `LDAP_GROUP_EDITOR_DN`, `LDAP_GROUP_VIEWER_DN` | grupos do AD que viram Admin, Editor e Viewer (`*` = todos) |
| `grafana.env` (Git) | `LDAP_ROOT_CA_CERT` | CA da empresa para LDAPS; o arquivo vai em `config/grafana/certs/` |
| `.env` | `LDAP_BIND_PASSWORD` | senha da conta de serviço |

O admin local (`admin`) continua entrando, para não perder o acesso se o AD cair. Para testar um usuário: *Administração → Autenticação → LDAP → Test user mapping*. Não salve alterações nessa tela: no Grafana 13 o que for salvo pela interface passa a valer no lugar do `ldap.toml`.

A senha da conta de serviço não pode ter aspas duplas (`"`) nem barra invertida (`\`), porque ela é inserida num arquivo TOML.

### 7. Validar

Em cada servidor, na pasta do repositório:

```bash
./scripts/validar.sh
ZABBIX_API_TOKEN=... ./scripts/validar.sh      # inclui o teste do MCP
```

O script confere:
- se os 9 containers estão de pé e o estado do HA (`zabbix_server -R ha_status`);
- `/ping` do web, `/catalogo/`, Grafana, Selenium, Java gateway e web service;
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
| 12 | LDAP | Login no Grafana com um usuário do AD de cada grupo | Entra com o papel do grupo (Admin/Editor/Viewer) |

## Operação

Na pasta do repositório, em cada servidor:

```bash
git pull && docker compose up -d --build          # aplicar o que mudou no Git
docker compose up -d                              # aplicar uma mudança no .env
docker compose pull --ignore-buildable && docker compose build --pull && docker compose up -d   # atualizar as imagens do trunk
docker compose ps
docker compose logs -f zabbix-server
docker compose down                               # parar a stack (os volumes com os dados ficam)
```

Para atualizar o trunk, faça **um servidor por vez**. Comece pelos standby e deixe o ativo por último. Quando o schema muda entre builds, o primeiro server a subir aplica o upgrade no banco.

## Pendências para o ambiente real

- Trocar os nomes fictícios: `DBxxx`, `SRVxxx01..03`, IPs `10.0.0.11..13`, `empresa.com.br`.
- Preencher o `.env` dos 3 servidores (modelo em `.env.example`).
- Configurar os pools no F5.
- Opcional: PSK entre proxies e server (`ZBX_TLS*` no `zabbix-proxy.env`), TLS com o banco (`ZBX_DBTLS*`).
