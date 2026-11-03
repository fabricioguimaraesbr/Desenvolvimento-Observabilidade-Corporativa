"""Fonte de dados fictícia (DEMO_MODE=true).

Gera um ambiente sintético com a mesma forma que o banco do Zabbix devolve,
para testar a interface e as regras sem acesso ao banco real. Os dados são
determinísticos (semente fixa).
"""
from __future__ import annotations

import random
import re
from typing import Iterator

APPS = {
    "Checkout": ("chk", ["Linux by Zabbix agent", "Nginx by Zabbix agent", "Java JMX", "Website certificate by Zabbix agent 2"]),
    "E-commerce Web": ("ecom", ["Linux by Zabbix agent", "Nginx by Zabbix agent", "Website certificate by Zabbix agent 2"]),
    "App Mobile BFF": ("bff", ["Linux by Zabbix agent", "Docker by Zabbix agent 2"]),
    "Pagamentos": ("pay", ["Linux by Zabbix agent", "Java JMX", "RabbitMQ node by HTTP"]),
    "Estoque": ("stk", ["Linux by Zabbix agent", "PostgreSQL by Zabbix agent 2"]),
    "PDV Lojas": ("pdv", ["Windows by Zabbix agent active", "ICMP Ping"]),
    "Centro de Distribuição": ("cd", ["Windows by Zabbix agent", "ICMP Ping", "Generic by SNMP"]),
    "ERP": ("erp", ["Linux by Zabbix agent", "Oracle by ODBC"]),
    "CRM": ("crm", ["Windows by Zabbix agent", "MSSQL by ODBC"]),
    "Cartão Private Label": ("crt", ["Linux by Zabbix agent", "Java JMX", "Oracle by ODBC"]),
    "Seguros e Serviços": ("seg", ["Linux by Zabbix agent", "Apache Tomcat by JMX"]),
    "Integrações (ESB)": ("esb", ["Linux by Zabbix agent", "Apache Kafka by JMX", "RabbitMQ node by HTTP"]),
    "Data Lake": ("dl", ["Linux by Zabbix agent", "Hadoop by HTTP"]),
    "Rede Lojas": ("rtr", ["Cisco IOS by SNMP", "ICMP Ping"]),
    "Rede Datacenter": ("sw", ["Cisco IOS by SNMP", "Arista by SNMP"]),
    "Kubernetes Produção": ("k8s", ["Kubernetes nodes by HTTP", "Kubernetes cluster state by HTTP"]),
    "Banco de Dados Core": ("db", ["PostgreSQL by Zabbix agent 2", "Linux by Zabbix agent"]),
    "Mensageria": ("mq", ["RabbitMQ node by HTTP", "Linux by Zabbix agent"]),
    "Portal do Colaborador": ("rh", ["Windows by Zabbix agent", "IIS by Zabbix agent"]),
    "Frete e Logística": ("frt", ["Linux by Zabbix agent", "Docker by Zabbix agent 2"]),
}

# chave base -> (tipo de item, nome exemplo, itens por host (min,max), parâmetros exemplo)
FAMILIES = {
    "Linux by Zabbix agent": [("system.cpu.util", 0, "CPU utilization", (8, 12), ["", "user", "system"]),
                              ("vfs.fs.dependent.size", 18, "FS [/]: Space: Used", (10, 40), ["/", "/var", "/opt/app"]),
                              ("net.if.in", 0, "Interface eth0: Bits received", (4, 16), ["eth0", "ens192"]),
                              ("vm.memory.size", 0, "Available memory", (4, 6), ["available", "total"]),
                              ("proc.num", 0, "Number of processes", (2, 4), ["", "java", "nginx"]),
                              ("system.uptime", 0, "System uptime", (1, 1), [""])],
    "Windows by Zabbix agent": [("perf_counter_en", 0, "CPU utilization", (10, 20), ["\\Processor Information(_total)\\% Processor Time"]),
                                ("vfs.fs.size", 0, "FS [C:]: Space: Used", (6, 12), ["C:", "D:"]),
                                ("service.info", 0, "State of service \"Spooler\"", (20, 60), ["Spooler", "W3SVC", "PDVService"])],
    "Windows by Zabbix agent active": [("perf_counter_en", 7, "CPU utilization", (10, 20), ["\\Processor(_total)\\% Processor Time"]),
                                       ("service.info", 7, "State of service \"PDVService\"", (10, 30), ["PDVService", "SitefService"])],
    "Nginx by Zabbix agent": [("web.page.get", 0, "Nginx: Get stub status page", (1, 2), ["localhost/basic_status"]),
                              ("nginx.connections.active", 18, "Nginx: Connections active", (6, 10), [""])],
    "Java JMX": [("jmx", 16, "Heap memory used", (30, 60), ["java.lang:type=Memory,HeapMemoryUsage.used", "Catalina:type=ThreadPool"])],
    "Apache Tomcat by JMX": [("jmx", 16, "Tomcat: Threads busy", (20, 40), ["Catalina:type=ThreadPool,name=\"http-nio-8080\""])],
    "Website certificate by Zabbix agent 2": [("web.certificate.get", 0, "Cert: Get", (1, 1), ["loja.exemplo.com.br,443"]),
                                              ("cert.not_after", 18, "Cert: Expires on", (3, 4), [""])],
    "Docker by Zabbix agent 2": [("docker.container_info", 0, "Container: Get info", (20, 80), ["/checkout-api", "/frete-worker"]),
                                 ("docker.containers.running", 0, "Containers running", (1, 2), [""])],
    "RabbitMQ node by HTTP": [("rabbitmq.queue.messages", 18, "Queue pedidos: Messages", (20, 120), ["pedidos", "pagamentos.retorno", "estoque.reserva"])],
    "PostgreSQL by Zabbix agent 2": [("pgsql.connections", 0, "Connections sum", (10, 20), ["tcp://localhost:5432"]),
                                     ("pgsql.db.size", 18, "DB estoque: Database size", (6, 30), ["estoque", "pedidos"])],
    "Oracle by ODBC": [("db.odbc.select", 11, "Oracle: Tablespace USERS used", (40, 120), ["tablespace_users", "sessions"])],
    "MSSQL by ODBC": [("db.odbc.get", 11, "MSSQL: Batch requests/sec", (30, 90), ["mssql.perf"])],
    "ICMP Ping": [("icmpping", 3, "ICMP ping", (1, 1), [""]), ("icmppingsec", 3, "ICMP response time", (1, 1), [""]),
                  ("icmppingloss", 3, "ICMP loss", (1, 1), [""])],
    "Generic by SNMP": [("system.uptime", 20, "Uptime", (1, 1), [""]), ("net.if.status", 20, "Interface Gi0/1: Operational status", (4, 24), ["ifOperStatus.1"])],
    "Cisco IOS by SNMP": [("net.if.in", 20, "Interface Gi0/1: Bits received", (40, 200), ["ifHCInOctets.1"]),
                          ("sensor.temp.value", 20, "Temperature", (2, 6), ["ciscoEnvMonTemperatureValue.1"])],
    "Arista by SNMP": [("net.if.in", 20, "Interface Ethernet1: Bits received", (80, 300), ["ifHCInOctets.1"])],
    "Kubernetes nodes by HTTP": [("kube.node.cpu", 18, "Node CPU usage", (20, 60), ["worker-01"]),
                                 ("kube.pod.phase", 18, "Pod checkout-api: Status", (50, 400), ["prod/checkout-api", "prod/frete-api"])],
    "Kubernetes cluster state by HTTP": [("kube.deployment.replicas", 18, "Deployment checkout-api: Replicas", (40, 200), ["prod/checkout-api"])],
    "Apache Kafka by JMX": [("jmx", 16, "Kafka: Messages in per second", (40, 100), ["kafka.server:type=BrokerTopicMetrics"])],
    "Hadoop by HTTP": [("hadoop.namenode.capacity", 19, "NameNode: Capacity remaining", (20, 60), [""])],
    "IIS by Zabbix agent": [("perf_counter_en", 0, "IIS: Current connections", (10, 30), ["\\Web Service(_Total)\\Current Connections"])],
}

TRIGGER_TEMPLATES = [
    ("High CPU utilization on {HOST.NAME}", 2), ("Disk space is low on {HOST.NAME}", 3),
    ("{HOST.NAME} is unavailable by ICMP", 4), ("Zabbix agent is not available on {HOST.NAME}", 3),
    ("High memory utilization on {HOST.NAME}", 2), ("{HOST.NAME} has been restarted", 1),
    ("Service is down on {HOST.NAME}", 4), ("Certificate expires in less than 7 days", 3),
    ("Fila com mensagens acumuladas", 3), ("Tempo de resposta acima do SLA", 4),
    ("Indisponibilidade total do serviço", 5), ("Pod em CrashLoopBackOff", 4),
    ("Interface down", 3), ("Too many connections", 2), ("Tablespace above 90%", 3),
]


class DemoSource:
    name = "demo"

    def __init__(self, *_args, seed: int = 42):
        r = random.Random(seed)
        self._groups: list[tuple] = []
        self._hosts: list[tuple] = []
        self._hg: list[tuple] = []
        self._ht: list[tuple] = []
        self._tags: list[tuple] = []
        self._macros: list[tuple] = []
        self._ifaces: list[tuple] = []
        self._itypes: list[tuple] = []
        self._fams: list[tuple] = []      # hostid, base, total, sample, [full keys]
        self._itags: list[tuple] = []
        self._triggers: list[tuple] = []
        self._trig_items: dict[int, list[str]] = {}  # triggerid -> chaves usadas

        templ_ids: dict[str, int] = {}
        gid, hid, tid = 1000, 10000, 100000
        infra_groups = ["Linux servers", "Windows servers", "Network devices", "Discovered hosts", "Zabbix servers"]
        for g in list(APPS) + infra_groups:
            gid += 1
            self._groups.append((gid, f"APP/{g}" if g in APPS else g))
        gmap = {name.split("/", 1)[-1]: g for g, name in self._groups}

        for app, (prefix, templates) in APPS.items():
            n_hosts = r.randint(6, 140) if prefix not in {"pdv", "rtr"} else r.randint(400, 900)
            for n in range(1, n_hosts + 1):
                hid += 1
                env = r.choices(["prd", "hml", "dev"], [7, 2, 1])[0]
                host = f"{prefix}-{env}-{n:03d}" if prefix not in {"pdv", "rtr"} else f"{prefix}-loja{n:04d}"
                status = 1 if r.random() < 0.04 else 0
                maint = 1 if r.random() < 0.03 else 0
                flags = 4 if prefix == "k8s" else 0
                proxy = r.choice(["proxy-dc-sp", "proxy-dc-rs", "proxy-lojas-01", "proxy-lojas-02", ""])
                self._hosts.append((hid, host, host.upper() if prefix == "pdv" else host, status, maint, flags, proxy, ""))
                self._hg.append((hid, gmap[app]))
                os_group = "Windows servers" if any("Windows" in t for t in templates) else (
                    "Network devices" if any("SNMP" in t for t in templates) else "Linux servers")
                self._hg.append((hid, gmap[os_group]))
                self._tags += [(hid, "ambiente", {"prd": "produção", "hml": "homologação", "dev": "desenvolvimento"}[env]),
                               (hid, "servico", app.lower())]
                if r.random() < 0.3:
                    self._macros.append((hid, "{$APP.NAME}", app))
                ip = f"10.{r.randint(1, 250)}.{r.randint(0, 255)}.{r.randint(1, 254)}"
                itype = 2 if "SNMP" in " ".join(templates) else 1
                avail = r.choices([1, 2, 0], [92, 5, 3])[0]
                self._ifaces.append((hid, itype, ip, f"{host}.corp.local", "161" if itype == 2 else "10050", avail))

                host_fams = []
                # Hosts de banco também servem outras aplicações (para testar regras parciais)
                for t in templates:
                    if t not in templ_ids:
                        templ_ids[t] = 50000 + len(templ_ids)
                    self._ht.append((hid, templ_ids[t], t))
                    for base, typ, sample, (lo, hi), params in FAMILIES.get(t, []):
                        total = r.randint(lo, hi)
                        keys = [f"{base}[{p}]" if p else base for p in params]
                        if prefix == "db" and base.startswith("pgsql.db"):
                            keys += ["pgsql.db.size[checkout]", "pgsql.db.size[pagamentos]"]
                        self._fams.append((hid, base, total, sample, keys))
                        host_fams.append(keys)
                        unsup = r.randint(0, max(1, total // 15)) if r.random() < 0.12 else 0
                        disabled = r.randint(0, total // 10) if r.random() < 0.2 else 0
                        self._itypes.append((hid, typ, 0, total - disabled, unsup))
                        if disabled:
                            self._itypes.append((hid, typ, 1, disabled, 0))
                        comp = base.split(".")[0]
                        self._itags.append((hid, "component", {"system": "cpu", "vfs": "storage", "net": "network",
                                                               "vm": "memory"}.get(comp, comp), total))
                for _ in range(r.randint(3, 14)):
                    tid += 1
                    desc, prio = r.choice(TRIGGER_TEMPLATES)
                    value = 1 if r.random() < 0.03 else 0
                    tstatus = 1 if r.random() < 0.05 else 0
                    self._triggers.append((tid, hid, desc, prio, tstatus, value))
                    self._trig_items[tid] = r.choice(host_fams) if host_fams else []

        # Hosts legados sem host group de aplicação (aparecem em "Hosts sem aplicação")
        for n in range(1, 38):
            hid += 1
            host = f"srv-legado-{n:03d}"
            self._hosts.append((hid, host, host, 0, 0, 0, "proxy-dc-sp", "Servidor sem dono definido"))
            self._hg.append((hid, gmap["Linux servers"]))
            self._ht.append((hid, templ_ids["Linux by Zabbix agent"], "Linux by Zabbix agent"))
            self._ifaces.append((hid, 1, f"10.10.9.{n}", "", "10050", r.choice([1, 1, 2])))
            for base, typ, sample, (lo, hi), params in FAMILIES["Linux by Zabbix agent"]:
                total = r.randint(lo, hi)
                self._fams.append((hid, base, total, sample, [base]))
                self._itypes.append((hid, typ, 0, total, 0))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def close(self):
        pass

    def version(self) -> str:
        return "7000000 (demo)"

    def hosts(self) -> Iterator[tuple]: return iter(self._hosts)
    def groups(self) -> Iterator[tuple]: return iter(self._groups)
    def host_groups(self) -> Iterator[tuple]: return iter(self._hg)
    def host_templates(self) -> Iterator[tuple]: return iter(self._ht)
    def host_tags(self) -> Iterator[tuple]: return iter(self._tags)
    def host_macros(self) -> Iterator[tuple]: return iter(self._macros)
    def interfaces(self) -> Iterator[tuple]: return iter(self._ifaces)
    def item_types(self) -> Iterator[tuple]: return iter(self._itypes)
    def item_families(self) -> Iterator[tuple]: return (f[:4] for f in self._fams)
    def item_tags(self) -> Iterator[tuple]: return iter(self._itags)
    def triggers(self) -> Iterator[tuple]: return iter(self._triggers)

    def match_items(self, keys: list[str], names: list[str]) -> tuple[list[tuple], set[int]]:
        kp = [re.compile(k, re.I) for k in keys]
        np_ = [re.compile(n, re.I) for n in names]
        fams = []
        for hid, base, total, sample, full in self._fams:
            hits = [k for k in full if any(p.search(k) for p in kp)]
            if hits or any(p.search(sample) for p in np_):
                fams.append((hid, base, max(1, total // max(1, len(full))) * max(1, len(hits) or 1), sample))
        trig = {tid for tid, ks in self._trig_items.items() if any(p.search(k) for k in ks for p in kp)}
        return fams, trig
