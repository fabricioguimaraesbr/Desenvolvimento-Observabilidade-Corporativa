"""Monta o catálogo (SQLite) a partir da fonte (banco do Zabbix ou demo).

O catálogo é gravado num arquivo temporário e trocado de forma atômica no
final, então a interface continua respondendo durante a coleta.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.rules import AppRule, Rules, load_rules, slugify
from app.settings import Settings

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE hosts (
    hostid INTEGER PRIMARY KEY, host TEXT, name TEXT, status INTEGER, maintenance INTEGER,
    flags INTEGER, proxy TEXT, description TEXT,
    ip TEXT DEFAULT '', dns TEXT DEFAULT '', iface_type INTEGER, available INTEGER DEFAULT 0,
    items_total INTEGER DEFAULT 0, items_enabled INTEGER DEFAULT 0, items_unsupported INTEGER DEFAULT 0,
    triggers_total INTEGER DEFAULT 0, triggers_problem INTEGER DEFAULT 0
);
CREATE TABLE groups (groupid INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE host_groups (hostid INTEGER, groupid INTEGER);
CREATE TABLE host_templates (hostid INTEGER, templateid INTEGER, name TEXT);
CREATE TABLE host_tags (hostid INTEGER, tag TEXT, value TEXT);
CREATE TABLE item_types (hostid INTEGER, type INTEGER, status INTEGER, total INTEGER, unsupported INTEGER);
CREATE TABLE item_families (hostid INTEGER, key_base TEXT, total INTEGER, sample_name TEXT);
CREATE TABLE item_tags (hostid INTEGER, tag TEXT, value TEXT, total INTEGER);
-- description: nome com {HOST.NAME} resolvido; raw: nome original (usado para agrupar)
CREATE TABLE triggers (triggerid INTEGER, hostid INTEGER, description TEXT, priority INTEGER,
                       status INTEGER, value INTEGER, raw TEXT);
CREATE TABLE apps (app_id INTEGER PRIMARY KEY, name TEXT, slug TEXT UNIQUE, description TEXT,
                   owner TEXT, contact TEXT, source TEXT);
CREATE TABLE app_hosts (app_id INTEGER, hostid INTEGER, scope TEXT, matched_by TEXT,
                        PRIMARY KEY (app_id, hostid));
CREATE TABLE app_item_families (app_id INTEGER, hostid INTEGER, key_base TEXT, total INTEGER, sample_name TEXT);
CREATE TABLE app_triggers (app_id INTEGER, triggerid INTEGER, hostid INTEGER);
CREATE TABLE app_stats (
    app_id INTEGER PRIMARY KEY, hosts INTEGER, hosts_partial INTEGER, hosts_disabled INTEGER,
    hosts_unavailable INTEGER, hosts_maintenance INTEGER, items INTEGER, items_unsupported INTEGER,
    triggers INTEGER, problems INTEGER, templates INTEGER,
    sev0 INTEGER, sev1 INTEGER, sev2 INTEGER, sev3 INTEGER, sev4 INTEGER, sev5 INTEGER
);
"""

INDEXES = """
CREATE INDEX ix_hg_host ON host_groups(hostid);
CREATE INDEX ix_hg_group ON host_groups(groupid);
CREATE INDEX ix_ht_host ON host_templates(hostid);
CREATE INDEX ix_htag_host ON host_tags(hostid);
CREATE INDEX ix_it_host ON item_types(hostid);
CREATE INDEX ix_if_host ON item_families(hostid);
CREATE INDEX ix_if_key ON item_families(key_base);
CREATE INDEX ix_itag_host ON item_tags(hostid);
CREATE INDEX ix_tr_host ON triggers(hostid);
CREATE INDEX ix_tr_id ON triggers(triggerid);
CREATE INDEX ix_ah_host ON app_hosts(hostid);
CREATE INDEX ix_aif_app ON app_item_families(app_id, hostid);
CREATE INDEX ix_at_app ON app_triggers(app_id, hostid);
CREATE INDEX ix_hosts_name ON hosts(name);
"""

_MACRO_HOST = re.compile(r"\{HOST\.(?:NAME|HOST)\d?\}")

_lock = threading.Lock()
_state: dict = {"running": False, "last_error": "", "last_started": None, "last_finished": None}


def state() -> dict:
    return dict(_state)


def _open_source(s: Settings):
    if s.demo_mode:
        from app.collector.demo_source import DemoSource
        return DemoSource()
    from app.collector.zabbix_source import ZabbixSource
    return ZabbixSource(s)


def _bulk(db: sqlite3.Connection, sql: str, rows, size: int = 50000) -> int:
    n, buf = 0, []
    for r in rows:
        buf.append(r)
        if len(buf) >= size:
            db.executemany(sql, buf)
            n += len(buf)
            buf.clear()
    if buf:
        db.executemany(sql, buf)
        n += len(buf)
    return n


def build_catalog(s: Settings, rules: Rules | None = None) -> dict:
    """Executa uma coleta completa. Retorna estatísticas da execução."""
    if not _lock.acquire(blocking=False):
        raise RuntimeError("Já existe uma coleta em andamento")
    t0 = time.monotonic()
    _state.update(running=True, last_error="", last_started=datetime.now(timezone.utc).isoformat())
    s.data_dir.mkdir(parents=True, exist_ok=True)
    tmp = s.catalog_path.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    try:
        rules = rules or load_rules(s.rules_file)
        db = sqlite3.connect(tmp)
        db.executescript(SCHEMA)
        timings: dict[str, float] = {}

        def step(name: str):
            timings[name] = round(time.monotonic() - t0, 1)
            log.info("coleta: %s (%.1fs)", name, timings[name])

        with _open_source(s) as src:
            version = src.version()
            _bulk(db, "INSERT INTO hosts(hostid,host,name,status,maintenance,flags,proxy,description) "
                      "VALUES (?,?,?,?,?,?,?,?)", src.hosts())
            step("hosts")
            _bulk(db, "INSERT INTO groups VALUES (?,?)", src.groups())
            _bulk(db, "INSERT INTO host_groups VALUES (?,?)", src.host_groups())
            _bulk(db, "INSERT INTO host_templates VALUES (?,?,?)", src.host_templates())
            _bulk(db, "INSERT INTO host_tags VALUES (?,?,?)", src.host_tags())
            macros = defaultdict(list)
            for hid, macro, value in src.host_macros():
                macros[hid].append((macro, value or ""))
            # interface: prioriza agente (1), depois SNMP (2), JMX (4), IPMI (3)
            prio = {1: 0, 2: 1, 4: 2, 3: 3}
            best: dict[int, tuple] = {}
            for hid, itype, ip, dns, port, avail in src.interfaces():
                cur = best.get(hid)
                if cur is None or prio.get(itype, 9) < prio.get(cur[0], 9):
                    best[hid] = (itype, ip or "", dns or "", avail or 0)
            db.executemany("UPDATE hosts SET iface_type=?, ip=?, dns=?, available=? WHERE hostid=?",
                           [(v[0], v[1], v[2], v[3], k) for k, v in best.items()])
            step("grupos, templates, tags, interfaces")

            _bulk(db, "INSERT INTO item_types VALUES (?,?,?,?,?)", src.item_types())
            step("itens por tipo")
            _bulk(db, "INSERT INTO item_families VALUES (?,?,?,?)", src.item_families())
            step("famílias de itens")
            _bulk(db, "INSERT INTO item_tags VALUES (?,?,?,?)", src.item_tags())
            step("tags de itens")

            names = dict(db.execute("SELECT hostid, name FROM hosts"))

            def tr_rows():
                for tid, hid, raw, prio_, status, value in src.triggers():
                    desc = raw or ""
                    if hid in names and "{" in desc:
                        desc = _MACRO_HOST.sub(names[hid], desc)
                    yield (tid, hid, desc, prio_, status, value, raw or "")
            _bulk(db, "INSERT INTO triggers VALUES (?,?,?,?,?,?,?)", tr_rows())
            step("triggers")

            db.executescript(INDEXES)
            db.executescript("""
                UPDATE hosts SET
                  items_total = COALESCE((SELECT SUM(total) FROM item_types t WHERE t.hostid = hosts.hostid), 0),
                  items_enabled = COALESCE((SELECT SUM(total) FROM item_types t WHERE t.hostid = hosts.hostid AND t.status = 0), 0),
                  items_unsupported = COALESCE((SELECT SUM(unsupported) FROM item_types t WHERE t.hostid = hosts.hostid), 0),
                  triggers_total = COALESCE((SELECT COUNT(*) FROM triggers t WHERE t.hostid = hosts.hostid), 0),
                  triggers_problem = COALESCE((SELECT COUNT(*) FROM triggers t WHERE t.hostid = hosts.hostid
                                                AND t.value = 1 AND t.status = 0), 0);
            """)
            step("totais por host")

            n_apps = _apply_rules(db, src, rules, macros)
            step("regras de aplicação")

        _compute_stats(db)
        totals = db.execute("""SELECT COUNT(*), SUM(items_total), SUM(triggers_total),
                                      SUM(status = 0), SUM(available = 2 AND status = 0)
                                 FROM hosts""").fetchone()
        unmapped = db.execute("SELECT COUNT(*) FROM hosts WHERE hostid NOT IN (SELECT hostid FROM app_hosts)").fetchone()[0]
        finished = datetime.now(timezone.utc).isoformat()
        meta = {
            "collected_at": finished,
            "duration_s": f"{time.monotonic() - t0:.1f}",
            "source": src.name,
            "zabbix_db_version": version,
            "hosts": totals[0] or 0, "items": totals[1] or 0, "triggers": totals[2] or 0,
            "hosts_enabled": totals[3] or 0, "hosts_unavailable": totals[4] or 0,
            "apps": n_apps, "hosts_unmapped": unmapped,
            "timings": json.dumps(timings),
        }
        db.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
        db.commit()
        db.execute("ANALYZE")
        db.close()
        os.replace(tmp, s.catalog_path)
        _state.update(last_finished=finished)
        log.info("coleta concluída em %ss: %s hosts, %s itens, %s aplicações",
                 meta["duration_s"], meta["hosts"], meta["items"], n_apps)
        return meta
    except Exception as exc:
        _state["last_error"] = f"{type(exc).__name__}: {exc}"
        log.exception("falha na coleta")
        if tmp.exists():
            tmp.unlink()
        raise
    finally:
        _state["running"] = False
        _lock.release()


# --------------------------------------------------------------------- regras
def _apply_rules(db: sqlite3.Connection, src, rules: Rules, macros: dict) -> int:
    groups = dict(db.execute("SELECT groupid, name FROM groups"))
    host_groups = defaultdict(list)
    for hid, gid in db.execute("SELECT hostid, groupid FROM host_groups"):
        if gid in groups:
            host_groups[hid].append(groups[gid])
    host_info = {hid: (host, name) for hid, host, name in db.execute("SELECT hostid, host, name FROM hosts")}
    host_tpl = defaultdict(list)
    for hid, name in db.execute("SELECT hostid, name FROM host_templates"):
        host_tpl[hid].append(name)
    host_tags = defaultdict(list)
    for hid, tag, value in db.execute("SELECT hostid, tag, value FROM host_tags"):
        host_tags[hid].append((tag, value or ""))

    # app -> {"meta": AppRule|None, "source": set, "hosts": {hid: (scope, set(reasons))},
    #         "fams": [(hid, base, total, sample)], "trig": set((tid, hid))}
    apps: dict[str, dict] = {}

    def app(name: str, source: str) -> dict:
        key = name.casefold()
        if key not in apps:
            apps[key] = {"name": name, "rule": None, "source": set(), "hosts": {}, "fams": [], "trig": set()}
        apps[key]["source"].add(source)
        return apps[key]

    def add_host(a: dict, hid: int, scope: str, reason: str):
        cur = a["hosts"].get(hid)
        if cur is None:
            a["hosts"][hid] = [scope, {reason}]
        else:
            if scope == "host":
                cur[0] = "host"
            cur[1].add(reason)

    # 1) aplicações automáticas a partir dos host groups
    group_app = {gname: rules.auto.app_name_for_group(gname) for gname in groups.values()}
    for hid, gnames in host_groups.items():
        if hid not in host_info:
            continue
        for g in gnames:
            name = group_app.get(g)
            if name:
                add_host(app(name, "host group"), hid, "host", f"host group {g}")

    # 2) aplicações declaradas
    triggers_by_desc: list[tuple] | None = None
    for rule in rules.apps:
        a = app(rule.name, "regra")
        a["rule"] = rule
        for hid, (host, vname) in host_info.items():
            reason = _host_match(rule, hid, host, vname, host_groups, host_tags, macros, host_tpl)
            if reason:
                add_host(a, hid, "host", reason)

        if rule.triggers:
            if triggers_by_desc is None:
                triggers_by_desc = db.execute("SELECT triggerid, hostid, description, raw FROM triggers").fetchall()
            for tid, hid, desc, raw in triggers_by_desc:
                if any(p.search(desc) or p.search(raw) for p in rule.triggers):
                    a["trig"].add((tid, hid))
                    add_host(a, hid, rule.partial_scope if rule.partial_scope == "host" else "partial", "triggers")

        if rule.has_item_rules:
            fams, tids = src.match_items(rule.item_keys, rule.item_names)
            for hid, base, total, sample in fams:
                if hid not in host_info:
                    continue
                a["fams"].append((hid, base, total, sample))
                add_host(a, hid, "host" if rule.partial_scope == "host" else "partial", "itens")
            if tids:
                tl = list(tids)
                for i in range(0, len(tl), 900):
                    chunk = tl[i:i + 900]
                    q = ",".join("?" * len(chunk))
                    for tid, hid in db.execute(f"SELECT triggerid, hostid FROM triggers WHERE triggerid IN ({q})", chunk):
                        a["trig"].add((tid, hid))

    # 3) grava
    n = 0
    used_slugs: set[str] = set()
    for key in sorted(apps, key=lambda k: apps[k]["name"].casefold()):
        a = apps[key]
        if not a["hosts"]:
            continue
        if any(p.search(a["name"]) for p in rules.hidden_apps):
            continue
        n += 1
        slug = slugify(a["name"])
        base, i = slug, 2
        while slug in used_slugs:
            slug, i = f"{base}-{i}", i + 1
        used_slugs.add(slug)
        r: AppRule | None = a["rule"]
        db.execute("INSERT INTO apps VALUES (?,?,?,?,?,?,?)",
                   (n, a["name"], slug, r.description if r else "", r.owner if r else "",
                    r.contact if r else "", ", ".join(sorted(a["source"]))))
        db.executemany("INSERT INTO app_hosts VALUES (?,?,?,?)",
                       [(n, hid, scope, ", ".join(sorted(reasons))) for hid, (scope, reasons) in a["hosts"].items()])
        partial = {hid for hid, (scope, _) in a["hosts"].items() if scope == "partial"}
        db.executemany("INSERT INTO app_item_families VALUES (?,?,?,?,?)",
                       [(n, *f) for f in a["fams"] if f[0] in partial])
        db.executemany("INSERT INTO app_triggers VALUES (?,?,?)",
                       [(n, tid, hid) for tid, hid in a["trig"] if hid in partial])
        db.execute("""INSERT INTO app_triggers
                      SELECT ?, t.triggerid, t.hostid FROM triggers t
                        JOIN app_hosts ah ON ah.hostid = t.hostid AND ah.app_id = ? AND ah.scope = 'host'""", (n, n))
    return n


def _host_match(rule: AppRule, hid, host, vname, host_groups, host_tags, macros, host_tpl) -> str | None:
    if rule.host_groups and any(p.search(g) for g in host_groups.get(hid, ()) for p in rule.host_groups):
        return "host group"
    if rule.host_names and any(p.search(host) or p.search(vname) for p in rule.host_names):
        return "nome do host"
    if rule.host_tags and any(kp.search(t) and vp.search(v) for t, v in host_tags.get(hid, ())
                              for kp, vp in rule.host_tags):
        return "tag do host"
    if rule.host_macros and any(kp.search(m) and vp.search(v) for m, v in macros.get(hid, ())
                                for kp, vp in rule.host_macros):
        return "macro do host"
    if rule.templates and any(p.search(t) for t in host_tpl.get(hid, ()) for p in rule.templates):
        return "template"
    return None


def _compute_stats(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TEMP TABLE app_items AS
          SELECT ah.app_id, SUM(h.items_enabled) AS items, SUM(h.items_unsupported) AS unsup
            FROM app_hosts ah JOIN hosts h ON h.hostid = ah.hostid
           WHERE ah.scope = 'host' GROUP BY ah.app_id
          UNION ALL
          SELECT app_id, SUM(total), 0 FROM app_item_families GROUP BY app_id;

        INSERT INTO app_stats
        SELECT a.app_id,
               (SELECT COUNT(*) FROM app_hosts ah WHERE ah.app_id = a.app_id),
               (SELECT COUNT(*) FROM app_hosts ah WHERE ah.app_id = a.app_id AND ah.scope = 'partial'),
               (SELECT COUNT(*) FROM app_hosts ah JOIN hosts h USING(hostid) WHERE ah.app_id = a.app_id AND h.status = 1),
               (SELECT COUNT(*) FROM app_hosts ah JOIN hosts h USING(hostid) WHERE ah.app_id = a.app_id AND h.status = 0 AND h.available = 2),
               (SELECT COUNT(*) FROM app_hosts ah JOIN hosts h USING(hostid) WHERE ah.app_id = a.app_id AND h.maintenance = 1),
               COALESCE((SELECT SUM(items) FROM app_items x WHERE x.app_id = a.app_id), 0),
               COALESCE((SELECT SUM(unsup) FROM app_items x WHERE x.app_id = a.app_id), 0),
               (SELECT COUNT(DISTINCT triggerid) FROM app_triggers t WHERE t.app_id = a.app_id),
               (SELECT COUNT(DISTINCT t.triggerid) FROM app_triggers at JOIN triggers t
                   ON t.triggerid = at.triggerid AND t.hostid = at.hostid
                 WHERE at.app_id = a.app_id AND t.value = 1 AND t.status = 0),
               (SELECT COUNT(DISTINCT ht.templateid) FROM app_hosts ah JOIN host_templates ht USING(hostid)
                 WHERE ah.app_id = a.app_id AND ah.scope = 'host'),
               0, 0, 0, 0, 0, 0
          FROM apps a;
    """)
    for sev in range(6):
        db.execute(f"""UPDATE app_stats SET sev{sev} = (
                         SELECT COUNT(DISTINCT t.triggerid) FROM app_triggers at
                           JOIN triggers t ON t.triggerid = at.triggerid AND t.hostid = at.hostid
                          WHERE at.app_id = app_stats.app_id AND t.priority = ? AND t.status = 0)""", (sev,))
