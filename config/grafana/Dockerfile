# Grafana com o plugin e o datasource do Zabbix provisionados. O provisioning vai
# dentro da imagem porque o Portainer CE não monta arquivos do repositório Git.
ARG GRAFANA_TAG=13.2.4
FROM grafana/grafana:${GRAFANA_TAG}
COPY provisioning /etc/grafana/provisioning
