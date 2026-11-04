# Zabbix web com o /catalogo/ no nginx.
ARG ZABBIX_TAG=alpine-trunk
FROM zabbix/zabbix-web-nginx-pgsql:${ZABBIX_TAG}
COPY --chown=1997:0 nginx.conf nginx_ssl.conf /etc/zabbix/
COPY --chown=1997:0 catalogo.conf /etc/nginx/catalogo/catalogo.conf
