# Grafana com o plugin do Zabbix, o datasource provisionado e o LDAP. Tudo vai
# dentro da imagem porque o Portainer CE não monta arquivos do repositório Git.
ARG GRAFANA_TAG=13.2.4
FROM grafana/grafana:${GRAFANA_TAG}

# Plugin instalado na construção: com GF_PLUGINS_PREINSTALL ele baixa em segundo
# plano e o provisionamento roda antes, derrubando o Grafana. Fica fora de
# /var/lib/grafana (volume) para atualizar junto com a imagem.
ARG ZABBIX_PLUGIN_VERSION=6.10.2
ENV GF_PATHS_PLUGINS=/var/lib/grafana-plugins
USER root
RUN mkdir -p "$GF_PATHS_PLUGINS" \
 && grafana cli --pluginsDir "$GF_PATHS_PLUGINS" plugins install alexanderzobnin-zabbix-app "$ZABBIX_PLUGIN_VERSION" \
 && chown -R 472:0 "$GF_PATHS_PLUGINS"
USER 472

COPY provisioning /etc/grafana/provisioning
COPY ldap.toml /etc/grafana/ldap.toml
COPY certs /etc/grafana/certs
