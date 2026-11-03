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
                                │      DBxxx      │  PostgreSQL do Zabbix 8.0 (zabbix, grafana)
                                │                 │  ClickHouse (APM: traces, métricas, logs OTel)
                                └─────────────────┘
```

- **Uma stack por servidor.** O `docker-compose.yml` da raiz é o mesmo nos 3. Cada servidor é uma **stack no Portainer** ligada a este repositório no GitLab; o que muda entre elas fica só nas variáveis da stack: `NODE_NAME`, `NODE_IP` e horário de coleta do catálogo.
- **HA do Zabbix server:** os 3 nós usam o mesmo banco; um fica ativo e os outros dois em standby. Se o ativo cai, um standby assume em cerca de 1 minuto. O frontend descobre sozinho o nó ativo pelo banco, por isso o web **não** tem `ZBX_SERVER_HOST`.
- **Proxies:** um por servidor (`proxy-SRVxxx01`..03), cada um conhecendo os 3 nós do HA. No frontend eles formam um **proxy group**, que redistribui os hosts se um proxy cair. Os proxies também recebem **APM** (OpenTelemetry, OTLP gRPC na porta 4317) e gravam no ClickHouse.
- **Banco:** PostgreSQL e ClickHouse ficam no **DBxxx** e já existem, com o schema do Zabbix 8.0 criado. A stack só aponta para eles pelas variáveis; não cria banco, usuário nem tabela.
- **Grafana:** usa banco compartilhado no PostgreSQL, então os 3 mostram os mesmos dashboards atrás do F5. O alerting roda em HA entre os 3 (porta 9094).

### Imagens

| Container | Imagem | Portas no servidor |
|---|---|---|
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-trunk` | 10051 |
| `zabbix-web` | build de `config/zabbix-web/` (`zabbix/zabbix-web-nginx-pgsql:alpine-trunk` + `/catalogo/`) | 80 |
| `zabbix-proxy` | `zabbix/zabbix-proxy-sqlite3:alpine-trunk` | 10061 (trapper), 4317 (APM/OTLP) |
| `zabbix-java-gateway` | `zabbix/zabbix-java-gateway:alpine-trunk` | só rede interna |
| `zabbix-web-service` | `zabbix/zabbix-web-service:alpine-trunk` | só rede interna |
| `zabbix-mcp-server` | `zabbix/zabbix-mcp-server:alpine-trunk` | 8444 |
| `selenium` | `selenium/standalone-chrome:latest` | só rede interna |
| `grafana` | build de `config/grafana/` (`grafana/grafana:13.2.4` + plugin e datasource do Zabbix) | 3000, 9094 (HA do alerting) |
| `catalogo` | build de `catalogo/` | 8088 (diagnóstico; o acesso normal é `/catalogo/` no web) |

> **Sobre o trunk:** `alpine-trunk` é o Zabbix **8.0 em desenvolvimento** (hoje 8.0.0rc3). A imagem muda a cada build. Para fixar uma versão, defina `ZABBIX_TAG` nas variáveis da stack, por exemplo para a tag 8.0 estável quando sair.

## Arquivos e diretórios

```
docker-compose.yml          stack de um servidor (igual nos 3)
portainer.env.example       lista das variáveis da stack no Portainer (senhas e valores de cada servidor)
monitoring-data/<container>/<container>.env   demais variáveis de cada container (sem senhas)
config/
  zabbix-web/               Dockerfile + nginx com o /catalogo/
  grafana/                  Dockerfile + plugin e datasource do Zabbix + LDAP (ldap.toml, certs/)
  zabbix-web-service/       perfil seccomp do Chrome (relatórios PDF)
scripts/validar.sh          checagens depois da subida (no shell do servidor)
catalogo/                   Catálogo de Monitoramento (código, regras, testes, README próprio)
```

### Onde fica cada variável

| Onde | O quê | Quem altera |
|---|---|---|
| **Variáveis da stack no Portainer** | senhas, token do Grafana e o que muda por servidor (`NODE_NAME`, `NODE_IP`, `CATALOGO_COLLECT_AT`). Lista completa em `portainer.env.example` | Pela tela do Portainer, em cada uma das 3 stacks |
| **`monitoring-data/*/*.env` no Git** | todo o resto: endereço do DBxxx, usuários do banco, desempenho do Zabbix, Grafana, MCP, Selenium | Commit no GitLab; o Portainer aplica nas 3 stacks |
| **`catalogo/config/rules.yaml` no Git** | regras do catálogo | Commit no GitLab |

**Nunca coloque senha nos arquivos do Git.** No `docker-compose.yml`, cada senha vem de uma variável da stack e é obrigatória: se faltar, o Portainer recusa o deploy dizendo qual falta.

### Por que algumas configs viram imagem

O Portainer CE clona o repositório e roda o compose a partir dele, mas **não monta arquivos do repositório dentro dos containers** (isso é o recurso *relative path volumes*, só da edição Business). Por isso:
- o nginx do `/catalogo/` e o provisioning do Grafana entram em imagens construídas pela própria stack (`config/zabbix-web/` e `config/grafana/`);
- os dados ficam em **volumes nomeados** do Docker (`zabbix-proxy-data`, `grafana-data`, `catalogo-data` e as pastas de scripts do Zabbix). O Docker cria os volumes com o dono certo, então ninguém precisa entrar no Linux para criar pastas.

## Passo a passo

### 1. Pré-requisitos

No **DBxxx** (já existentes; só confira):
- os 3 servidores conseguem conectar no PostgreSQL (5432) e no ClickHouse (HTTP 8123);
- existe um database `grafana` com usuário para o Grafana;
- existe um usuário **somente leitura** no banco do Zabbix para o catálogo.

No **Portainer**: os 3 servidores cadastrados como ambientes, cada um com o **Portainer agent** instalado à parte. O agent não fica nesta stack: se ficasse, todo redeploy derrubaria a conexão do próprio Portainer com o servidor no meio do deploy.

No **GitLab**: um usuário ou *deploy token* com leitura no repositório, para o Portainer clonar.

### 2. Ajustar o que fica no Git

Troque os nomes fictícios em `monitoring-data/*/*.env` (`DBxxx`, `empresa.com.br`, redes do MCP) e faça commit. Esses arquivos são **iguais nos 3 servidores**.

### 3. Criar uma stack por servidor no Portainer

Em cada um dos 3 ambientes: *Stacks → Add stack → Repository*.

| Campo | Valor |
|---|---|
| Name | `monitoramento` |
| Repository URL | URL do repositório no GitLab |
| Repository reference | `refs/heads/HML-Corp` |
| Compose path | `docker-compose.yml` |
| Authentication | usuário + token do GitLab |
| GitOps updates | ligado (polling, ex.: 5 min, ou webhook do GitLab) |
| Environment variables | *Advanced mode*: cole `portainer.env.example` e preencha |

Nas variáveis, só `NODE_NAME`, `NODE_IP` e `CATALOGO_COLLECT_AT` mudam entre as 3 stacks; o resto é igual. A `GRAFANA_SECRET_KEY` **precisa** ser a mesma nas 3. O `ZABBIX_API_TOKEN` fica vazio até o passo 4.

O primeiro deploy demora mais porque constrói as imagens do Zabbix web, do Grafana e do catálogo.

**Atualizações:** um commit no GitLab chega às 3 stacks pelo GitOps. Se mudar algo que vai dentro de uma imagem (`config/zabbix-web/`, `config/grafana/`, `catalogo/`), confira no primeiro teste se o redeploy reconstrói a imagem; se não reconstruir, use *Pull and redeploy* na stack.

### 4. Configurar no frontend do Zabbix

1. Troque a senha do `Admin`.
2. **Proxies:** em *Administração → Proxies*, crie os proxies `proxy-SRVxxx01`, `proxy-SRVxxx02` e `proxy-SRVxxx03` (modo ativo) e um **proxy group** com os três (*Administração → Proxy groups*, mínimo online = 1). Monitore os hosts pelo proxy group.
3. **Token do Grafana:** crie um usuário de serviço com papel somente leitura e um token de API para ele. Coloque o token na variável `ZABBIX_API_TOKEN` das 3 stacks no Portainer e clique em *Update the stack*.
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
| Portainer | `LDAP_BIND_PASSWORD` | senha da conta de serviço |

O admin local (`admin`) continua entrando, para não perder o acesso se o AD cair. Para testar um usuário: *Administração → Autenticação → LDAP → Test user mapping*. Não salve alterações nessa tela: no Grafana 13 o que for salvo pela interface passa a valer no lugar do `ldap.toml`.

A senha da conta de serviço não pode ter aspas duplas (`"`) nem barra invertida (`\`), porque ela é inserida num arquivo TOML.

### 7. Validar

Pelo Portainer: na stack, todos os containers `running` e o `zabbix-web` `healthy`; os logs de cada container ficam no ícone de logs.

Quem tem acesso ao servidor pode rodar as checagens completas, na pasta de um clone do repositório:

```bash
./scripts/validar.sh
ZABBIX_API_TOKEN=... ./scripts/validar.sh      # inclui o teste do MCP
```

O script confere:
- se os 9 containers estão de pé e o estado do HA (`zabbix_server -R ha_status`);
- `/ping` do web, `/catalogo/`, Grafana, Portainer agent, Selenium, Java gateway e web service;
- erros recentes nos logs.

## Roteiro de testes de homologação

| # | Teste | Como | Esperado |
|---|---|---|---|
| 1 | HA | Portainer → container `zabbix-server` → *Console*: `zabbix_server -R ha_status` | 3 nós: 1 `active`, 2 `standby` |
| 2 | Failover | *Stop* no `zabbix-server` do nó ativo (Portainer); depois `ha_status` em outro | Um standby vira `active` em até ~1 min; o frontend segue funcionando. Depois, *Start* |
| 3 | Frontend em cada nó | `curl -I http://<IP>/` nos 3 | 200 nos 3 |
| 4 | Proxy group | *Administração → Proxies* | 3 proxies online; ao parar um (*Stop* no `zabbix-proxy`), os hosts dele passam para outro |
| 5 | Catálogo | `https://zabbix.empresa.com.br/catalogo/` | Lista as aplicações; `/catalogo` e `/catálogo` redirecionam |
| 6 | JMX | Host com interface JMX e template *Generic Java JMX* | Itens JMX coletando |
| 7 | Relatório | *Relatórios → Relatórios agendados → Testar* | PDF gerado e enviado |
| 8 | Browser item | Item do tipo *Browser* (ex.: template *Website by Browser*) | Item coletando via Selenium |
| 9 | MCP | `validar.sh` com `ZABBIX_API_TOKEN` | `tools/list` responde |
| 10 | Grafana | `https://grafana.empresa.com.br` → *Connections → Data sources → Zabbix → Test* | Datasource OK; mesmo dashboard visto pelos 3 nós |
| 11a | LDAP | Login no Grafana com um usuário do AD de cada grupo | Entra com o papel do grupo (Admin/Editor/Viewer) |
| 11 | APM | App com OpenTelemetry exportando para `<IP do proxy>:4317` | Traces aparecem no Zabbix |
| 12 | GitOps | Commit trocando um valor em `monitoring-data/` | As 3 stacks atualizam sozinhas |

## Operação

Tudo pelo Portainer, na stack de cada servidor:
- **Mudar uma senha ou valor do servidor:** *Environment variables* → *Update the stack*.
- **Mudar o resto:** commit no GitLab; o GitOps aplica nas 3 stacks.
- **Atualizar as imagens do trunk:** *Pull and redeploy*, um servidor por vez.
- **Dados:** ficam nos volumes nomeados; remover ou recriar a stack não apaga os volumes.

Para atualizar o trunk, faça **um servidor por vez**. Comece pelos standby e deixe o ativo por último. Quando o schema muda entre builds, o primeiro server a subir aplica o upgrade no banco.

## Pendências para o ambiente real

- Trocar os nomes fictícios: `DBxxx`, `SRVxxx01..03`, IPs `10.0.0.11..13`, `empresa.com.br`.
- Preencher as variáveis das 3 stacks no Portainer (`portainer.env.example`).
- Configurar os pools no F5.
- Opcional: PSK entre proxies e server (`ZBX_TLS*` no `zabbix-proxy.env`), TLS com o banco (`ZBX_DBTLS*`) e `AGENT_SECRET` do Portainer agent.
