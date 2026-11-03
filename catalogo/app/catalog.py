"""Consultas de leitura sobre o catálogo SQLite (usadas pela API e exportações)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ITEM_TYPES = {
    0: "Zabbix agent", 2: "Zabbix trapper", 3: "Simple check", 5: "Zabbix internal",
    7: "Zabbix agent (ativo)", 9: "Web item", 10: "External check", 11: "Database monitor",
    12: "IPMI agent", 13: "SSH agent", 14: "TELNET agent", 15: "Calculado", 16: "JMX agent",
    17: "SNMP trap", 18: "Dependente", 19: "HTTP agent", 20: "SNMP agent", 21: "Script", 22: "Browser",
}
SEVERITIES = ["Não classificada", "Informação", "Atenção", "Média", "Alta", "Desastre"]
AVAILABILITY = {0: "Desconhecida", 1: "Disponível", 2: "Indisponível"}
IFACE_TYPES = {1: "Agent", 2: "SNMP", 3: "IPMI", 4: "JMX"}


class CatalogMissing(Exception):
    pass


class Catalog:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def db(self):
        if not self.path.exists():
            raise CatalogMissing()
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _rows(cur) -> list[dict]:
        return [dict(r) for r in cur]

    @staticmethod
    def _like(q: str) -> str:
        q = (q or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{q}%"

    def _app(self, db, slug: str) -> dict | None:
        r = db.execute("""SELECT a.*, s.* FROM apps a JOIN app_stats s USING(app_id) WHERE a.slug = ?""",
                       (slug,)).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------- visão geral
    def summary(self) -> dict:
        with self.db() as db:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
            meta = {k: int(v) if v.isdigit() else v for k, v in meta.items()}
            meta["timings"] = json.loads(meta.get("timings", "{}"))
            sev = db.execute("""SELECT priority, COUNT(*) n FROM triggers WHERE status = 0
                                GROUP BY priority ORDER BY priority""").fetchall()
            types = db.execute("""SELECT type, SUM(total) n FROM item_types WHERE status = 0
                                  GROUP BY type ORDER BY n DESC""").fetchall()
            proxies = db.execute("""SELECT CASE proxy WHEN '' THEN 'Servidor (sem proxy)' ELSE proxy END proxy,
                                           COUNT(*) n FROM hosts GROUP BY proxy ORDER BY n DESC LIMIT 15""").fetchall()
            problems = db.execute("SELECT COUNT(*) FROM triggers WHERE status = 0 AND value = 1").fetchone()[0]
            unsupported = db.execute("SELECT SUM(items_unsupported) FROM hosts").fetchone()[0] or 0
        return {
            "meta": meta,
            "severities": [{"priority": r["priority"], "label": SEVERITIES[r["priority"]], "n": r["n"]} for r in sev],
            "item_types": [{"type": r["type"], "label": ITEM_TYPES.get(r["type"], str(r["type"])), "n": r["n"]} for r in types],
            "proxies": self._rows(proxies),
            "problems": problems,
            "items_unsupported": unsupported,
        }

    def list_apps(self, q: str = "", sort: str = "name") -> list[dict]:
        order = {"name": "a.name COLLATE NOCASE", "hosts": "s.hosts DESC", "items": "s.items DESC",
                 "triggers": "s.triggers DESC", "problems": "s.problems DESC"}.get(sort, "a.name COLLATE NOCASE")
        with self.db() as db:
            return self._rows(db.execute(f"""
                SELECT a.app_id, a.name, a.slug, a.description, a.owner, a.source, s.*
                  FROM apps a JOIN app_stats s USING(app_id)
                 WHERE a.name LIKE ? ESCAPE '\\' OR a.owner LIKE ? ESCAPE '\\'
                 ORDER BY {order}""", (self._like(q), self._like(q))))

    # ---------------------------------------------------------------- aplicação
    def app_detail(self, slug: str) -> dict | None:
        with self.db() as db:
            app = self._app(db, slug)
            if not app:
                return None
            aid = app["app_id"]
            types = db.execute("""
                SELECT it.type, SUM(it.total) n, SUM(it.unsupported) unsup
                  FROM app_hosts ah JOIN item_types it ON it.hostid = ah.hostid AND it.status = 0
                 WHERE ah.app_id = ? AND ah.scope = 'host' GROUP BY it.type ORDER BY n DESC""", (aid,)).fetchall()
            partial_items = db.execute("SELECT COALESCE(SUM(total),0) FROM app_item_families WHERE app_id = ?",
                                       (aid,)).fetchone()[0]
            templates = db.execute("""
                SELECT ht.name, COUNT(DISTINCT ht.hostid) hosts
                  FROM app_hosts ah JOIN host_templates ht ON ht.hostid = ah.hostid
                 WHERE ah.app_id = ? AND ah.scope = 'host' GROUP BY ht.name ORDER BY hosts DESC, ht.name""",
                                   (aid,)).fetchall()
            tags = db.execute("""
                SELECT t.tag, t.value, COUNT(DISTINCT t.hostid) hosts
                  FROM app_hosts ah JOIN host_tags t ON t.hostid = ah.hostid
                 WHERE ah.app_id = ? GROUP BY t.tag, t.value ORDER BY t.tag, hosts DESC LIMIT 200""",
                              (aid,)).fetchall()
            proxies = db.execute("""
                SELECT CASE h.proxy WHEN '' THEN 'Servidor (sem proxy)' ELSE h.proxy END proxy, COUNT(*) n
                  FROM app_hosts ah JOIN hosts h ON h.hostid = ah.hostid
                 WHERE ah.app_id = ? GROUP BY h.proxy ORDER BY n DESC""", (aid,)).fetchall()
            matched = db.execute("""SELECT matched_by, COUNT(*) n FROM app_hosts WHERE app_id = ?
                                    GROUP BY matched_by ORDER BY n DESC""", (aid,)).fetchall()
        types_out = [{"type": r["type"], "label": ITEM_TYPES.get(r["type"], str(r["type"])),
                      "n": r["n"], "unsupported": r["unsup"]} for r in types]
        if partial_items:
            types_out.append({"type": -1, "label": "Itens de hosts compartilhados", "n": partial_items, "unsupported": 0})
        app["severities"] = [{"priority": i, "label": SEVERITIES[i], "n": app[f"sev{i}"]} for i in range(6)]
        # "templates" deixa de ser a contagem (app_stats) e passa a ser a lista
        app.update(item_types=types_out, templates=self._rows(templates), tags=self._rows(tags),
                   proxies=self._rows(proxies), matched_by=self._rows(matched))
        return app

    def app_hosts(self, slug: str, q: str = "", status: str = "", page: int = 1, size: int = 50) -> dict | None:
        with self.db() as db:
            app = self._app(db, slug)
            if not app:
                return None
            where = ["ah.app_id = ?", "(h.name LIKE ? ESCAPE '\\' OR h.host LIKE ? ESCAPE '\\' OR h.ip LIKE ? ESCAPE '\\')"]
            params: list = [app["app_id"], self._like(q), self._like(q), self._like(q)]
            if status == "unavailable":
                where.append("h.available = 2 AND h.status = 0")
            elif status == "disabled":
                where.append("h.status = 1")
            elif status == "maintenance":
                where.append("h.maintenance = 1")
            elif status == "partial":
                where.append("ah.scope = 'partial'")
            w = " AND ".join(where)
            total = db.execute(f"SELECT COUNT(*) FROM app_hosts ah JOIN hosts h USING(hostid) WHERE {w}", params).fetchone()[0]
            rows = db.execute(f"""
                SELECT h.hostid, h.host, h.name, h.status, h.maintenance, h.available, h.ip, h.dns, h.proxy,
                       ah.scope, ah.matched_by,
                       CASE ah.scope WHEN 'host' THEN h.items_enabled
                            ELSE COALESCE((SELECT SUM(total) FROM app_item_families f
                                            WHERE f.app_id = ah.app_id AND f.hostid = h.hostid), 0) END items,
                       (SELECT COUNT(*) FROM app_triggers t WHERE t.app_id = ah.app_id AND t.hostid = h.hostid) triggers,
                       h.items_unsupported, h.triggers_problem,
                       (SELECT GROUP_CONCAT(name, ' | ') FROM host_templates ht WHERE ht.hostid = h.hostid) templates
                  FROM app_hosts ah JOIN hosts h USING(hostid)
                 WHERE {w} ORDER BY h.name COLLATE NOCASE LIMIT ? OFFSET ?""",
                              params + [size, (max(page, 1) - 1) * size]).fetchall()
        return {"total": total, "page": page, "size": size, "rows": self._rows(rows)}

    def app_items(self, slug: str, q: str = "", limit: int = 500) -> dict | None:
        with self.db() as db:
            app = self._app(db, slug)
            if not app:
                return None
            rows = db.execute("""
                SELECT key_base, SUM(total) items, COUNT(DISTINCT hostid) hosts, MIN(sample_name) sample_name
                  FROM (SELECT f.hostid, f.key_base, f.total, f.sample_name
                          FROM app_hosts ah JOIN item_families f ON f.hostid = ah.hostid
                         WHERE ah.app_id = ? AND ah.scope = 'host'
                        UNION ALL
                        SELECT hostid, key_base, total, sample_name FROM app_item_families WHERE app_id = ?)
                 WHERE key_base LIKE ? ESCAPE '\\' OR sample_name LIKE ? ESCAPE '\\'
                 GROUP BY key_base ORDER BY items DESC LIMIT ?""",
                              (app["app_id"], app["app_id"], self._like(q), self._like(q), limit)).fetchall()
            tags = db.execute("""
                SELECT it.tag, it.value, SUM(it.total) items
                  FROM app_hosts ah JOIN item_tags it ON it.hostid = ah.hostid
                 WHERE ah.app_id = ? AND ah.scope = 'host'
                 GROUP BY it.tag, it.value ORDER BY items DESC LIMIT 100""", (app["app_id"],)).fetchall()
        return {"families": self._rows(rows), "item_tags": self._rows(tags)}

    def app_triggers(self, slug: str, q: str = "", severity: int | None = None, problems: bool = False,
                     page: int = 1, size: int = 50) -> dict | None:
        with self.db() as db:
            app = self._app(db, slug)
            if not app:
                return None
            where = ["at.app_id = ?", "(t.raw LIKE ? ESCAPE '\\' OR t.description LIKE ? ESCAPE '\\')"]
            params: list = [app["app_id"], self._like(q), self._like(q)]
            if severity is not None:
                where.append("t.priority = ?")
                params.append(severity)
            if problems:
                where.append("t.value = 1 AND t.status = 0")
            w = " AND ".join(where)
            base = f"""FROM app_triggers at
                        JOIN triggers t ON t.triggerid = at.triggerid AND t.hostid = at.hostid
                        JOIN hosts h ON h.hostid = t.hostid WHERE {w}"""
            total = db.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            grouped = db.execute(f"""SELECT t.raw AS description, t.priority, COUNT(DISTINCT t.hostid) hosts,
                                            SUM(t.value = 1 AND t.status = 0) problems, SUM(t.status = 1) disabled
                                       {base} GROUP BY t.raw, t.priority
                                       ORDER BY t.priority DESC, hosts DESC LIMIT ? OFFSET ?""",
                                 params + [size, (max(page, 1) - 1) * size]).fetchall()
            n_groups = db.execute(f"SELECT COUNT(*) FROM (SELECT 1 {base} GROUP BY t.raw, t.priority)",
                                  params).fetchone()[0]
        out = self._rows(grouped)
        for r in out:
            r["severity"] = SEVERITIES[r["priority"]]
        return {"total": total, "groups": n_groups, "page": page, "size": size, "rows": out}

    # ------------------------------------------------------------------- host
    def host_detail(self, hostid: int) -> dict | None:
        with self.db() as db:
            h = db.execute("SELECT * FROM hosts WHERE hostid = ?", (hostid,)).fetchone()
            if not h:
                return None
            h = dict(h)
            h["groups"] = [r[0] for r in db.execute(
                "SELECT g.name FROM host_groups hg JOIN groups g USING(groupid) WHERE hg.hostid = ? ORDER BY g.name", (hostid,))]
            h["templates"] = [r[0] for r in db.execute(
                "SELECT name FROM host_templates WHERE hostid = ? ORDER BY name", (hostid,))]
            h["tags"] = self._rows(db.execute("SELECT tag, value FROM host_tags WHERE hostid = ? ORDER BY tag", (hostid,)))
            h["apps"] = self._rows(db.execute("""SELECT a.name, a.slug, ah.scope, ah.matched_by FROM app_hosts ah
                                                  JOIN apps a USING(app_id) WHERE ah.hostid = ? ORDER BY a.name""", (hostid,)))
            h["item_types"] = [{"label": ITEM_TYPES.get(r["type"], str(r["type"])), "n": r["n"], "unsupported": r["u"]}
                               for r in db.execute("""SELECT type, SUM(total) n, SUM(unsupported) u FROM item_types
                                                       WHERE hostid = ? AND status = 0 GROUP BY type ORDER BY n DESC""", (hostid,))]
            h["families"] = self._rows(db.execute("""SELECT key_base, total, sample_name FROM item_families
                                                      WHERE hostid = ? ORDER BY total DESC""", (hostid,)))
            tr = self._rows(db.execute("""SELECT description, priority, status, value FROM triggers
                                           WHERE hostid = ? ORDER BY priority DESC, description""", (hostid,)))
            for t in tr:
                t["severity"] = SEVERITIES[t["priority"]]
            h["triggers"] = tr
        h["availability"] = AVAILABILITY.get(h["available"], "Desconhecida")
        h["iface"] = IFACE_TYPES.get(h["iface_type"], "")
        return h

    def unmapped_hosts(self, q: str = "", page: int = 1, size: int = 50) -> dict:
        with self.db() as db:
            w = """h.hostid NOT IN (SELECT hostid FROM app_hosts)
                   AND (h.name LIKE ? ESCAPE '\\' OR h.host LIKE ? ESCAPE '\\')"""
            p = [self._like(q), self._like(q)]
            total = db.execute(f"SELECT COUNT(*) FROM hosts h WHERE {w}", p).fetchone()[0]
            rows = db.execute(f"""SELECT h.hostid, h.host, h.name, h.status, h.available, h.items_enabled items,
                                         (SELECT GROUP_CONCAT(g.name, ' | ') FROM host_groups hg JOIN groups g USING(groupid)
                                           WHERE hg.hostid = h.hostid) groups
                                    FROM hosts h WHERE {w} ORDER BY h.name COLLATE NOCASE LIMIT ? OFFSET ?""",
                              p + [size, (max(page, 1) - 1) * size]).fetchall()
        return {"total": total, "page": page, "size": size, "rows": self._rows(rows)}

    # ------------------------------------------------------------------- busca
    def search(self, q: str, limit: int = 12) -> dict:
        q = (q or "").strip()
        if len(q) < 2:
            return {"q": q, "apps": [], "hosts": [], "templates": [], "items": [], "triggers": []}
        like = self._like(q)
        with self.db() as db:
            apps = db.execute("""SELECT a.name, a.slug, s.hosts, s.items FROM apps a JOIN app_stats s USING(app_id)
                                  WHERE a.name LIKE ? ESCAPE '\\' OR a.owner LIKE ? ESCAPE '\\'
                                  ORDER BY s.hosts DESC LIMIT ?""", (like, like, limit)).fetchall()
            hosts = db.execute("""SELECT h.hostid, h.name, h.host, h.ip, h.status, h.available,
                                         (SELECT GROUP_CONCAT(a.name, ' | ') FROM app_hosts ah JOIN apps a USING(app_id)
                                           WHERE ah.hostid = h.hostid) apps
                                    FROM hosts h
                                   WHERE h.name LIKE ? ESCAPE '\\' OR h.host LIKE ? ESCAPE '\\'
                                      OR h.ip LIKE ? ESCAPE '\\' OR h.dns LIKE ? ESCAPE '\\'
                                   ORDER BY h.name LIMIT ?""", (like, like, like, like, limit)).fetchall()
            templates = db.execute("""SELECT name, COUNT(DISTINCT hostid) hosts FROM host_templates
                                       WHERE name LIKE ? ESCAPE '\\' GROUP BY name ORDER BY hosts DESC LIMIT ?""",
                                   (like, limit)).fetchall()
            items = db.execute("""SELECT key_base, MIN(sample_name) sample_name, SUM(total) items,
                                         COUNT(DISTINCT hostid) hosts
                                    FROM item_families
                                   WHERE key_base LIKE ? ESCAPE '\\' OR sample_name LIKE ? ESCAPE '\\'
                                   GROUP BY key_base ORDER BY items DESC LIMIT ?""", (like, like, limit)).fetchall()
            triggers = db.execute("""SELECT raw AS description, priority, COUNT(DISTINCT hostid) hosts,
                                            SUM(value = 1 AND status = 0) problems
                                       FROM triggers WHERE raw LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\'
                                      GROUP BY raw, priority ORDER BY hosts DESC LIMIT ?""",
                                  (like, like, limit)).fetchall()
        tr = self._rows(triggers)
        for t in tr:
            t["severity"] = SEVERITIES[t["priority"]]
        return {"q": q, "apps": self._rows(apps), "hosts": self._rows(hosts), "templates": self._rows(templates),
                "items": self._rows(items), "triggers": tr}

    def apps_for_template(self, name: str) -> list[dict]:
        with self.db() as db:
            return self._rows(db.execute("""
                SELECT a.name, a.slug, COUNT(DISTINCT ah.hostid) hosts
                  FROM host_templates ht JOIN app_hosts ah ON ah.hostid = ht.hostid AND ah.scope = 'host'
                  JOIN apps a USING(app_id) WHERE ht.name = ? GROUP BY a.app_id ORDER BY hosts DESC""", (name,)))

    def apps_for_item_key(self, key_base: str) -> list[dict]:
        with self.db() as db:
            return self._rows(db.execute("""
                SELECT a.name, a.slug, COUNT(DISTINCT x.hostid) hosts, SUM(x.total) items
                  FROM (SELECT ah.app_id, f.hostid, f.total FROM item_families f
                          JOIN app_hosts ah ON ah.hostid = f.hostid AND ah.scope = 'host' WHERE f.key_base = ?
                        UNION ALL
                        SELECT app_id, hostid, total FROM app_item_families WHERE key_base = ?) x
                  JOIN apps a USING(app_id) GROUP BY a.app_id ORDER BY items DESC""", (key_base, key_base)))

    # --------------------------------------------------------------- exportação
    def export_apps(self) -> list[dict]:
        rows = self.list_apps()
        return [{"Aplicação": r["name"], "Responsável": r["owner"], "Hosts": r["hosts"],
                 "Hosts compartilhados": r["hosts_partial"], "Hosts desativados": r["hosts_disabled"],
                 "Hosts indisponíveis": r["hosts_unavailable"], "Itens ativos": r["items"],
                 "Itens não suportados": r["items_unsupported"], "Triggers": r["triggers"],
                 "Em problema": r["problems"], "Templates": r["templates"],
                 **{f"Triggers {SEVERITIES[i]}": r[f"sev{i}"] for i in range(6)},
                 "Origem": r["source"]} for r in rows]

    def export_app(self, slug: str) -> dict[str, list[dict]] | None:
        d = self.app_detail(slug)
        if not d:
            return None
        hosts = self.app_hosts(slug, size=10_000_000)["rows"]
        items = self.app_items(slug, limit=100_000)["families"]
        trig = self.app_triggers(slug, size=10_000_000)["rows"]
        st = {0: "Ativo", 1: "Desativado"}
        return {
            "Resumo": [{"Campo": k, "Valor": v} for k, v in [
                ("Aplicação", d["name"]), ("Responsável", d["owner"]), ("Descrição", d["description"]),
                ("Hosts", d["hosts"]), ("Itens ativos", d["items"]), ("Triggers", d["triggers"]),
                ("Em problema", d["problems"]), ("Templates", len(d["templates"]))]],
            "Hosts": [{"Nome visível": h["name"], "Host": h["host"], "IP": h["ip"], "DNS": h["dns"],
                       "Status": st.get(h["status"], h["status"]),
                       "Disponibilidade": AVAILABILITY.get(h["available"], ""),
                       "Manutenção": "Sim" if h["maintenance"] else "Não", "Proxy": h["proxy"],
                       "Escopo": "Host inteiro" if h["scope"] == "host" else "Compartilhado (parcial)",
                       "Itens": h["items"], "Triggers": h["triggers"], "Templates": h["templates"] or "",
                       "Associado por": h["matched_by"]} for h in hosts],
            "Templates": [{"Template": t["name"], "Hosts": t["hosts"]} for t in d["templates"]],
            "Itens por chave": [{"Chave": f["key_base"], "Exemplo de nome": f["sample_name"],
                                 "Itens": f["items"], "Hosts": f["hosts"]} for f in items],
            "Triggers": [{"Trigger": t["description"], "Severidade": t["severity"], "Hosts": t["hosts"],
                          "Em problema": t["problems"], "Desativadas": t["disabled"]} for t in trig],
        }
