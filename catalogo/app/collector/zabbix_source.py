"""Leitura do banco do Zabbix 7.x e 8.0 (PostgreSQL / TimescaleDB).

Só tabelas de configuração são lidas (hosts, itens, triggers, tags...).
Nenhuma tabela de histórico/tendência é tocada, então o TimescaleDB não pesa
aqui. Todas as consultas rodam numa transação somente leitura e com
statement_timeout, e resultados grandes são lidos em streaming (cursor no
servidor) para não estourar memória com 1,5 milhão de itens.

Recomendação: aponte para uma réplica de leitura, se houver.
"""
from __future__ import annotations

import logging
from typing import Iterator, Sequence

import psycopg

from app.settings import Settings

log = logging.getLogger(__name__)

# flags: 0 = normal, 4 = criado por LLD. Protótipos (2) e regras LLD (1) ficam de fora.
_REAL = "(0, 4)"


class ZabbixSource:
    name = "zabbix-db"

    def __init__(self, s: Settings):
        self.conn = psycopg.connect(
            host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user,
            password=s.db_password, sslmode=s.db_sslmode,
            application_name="catalogo-monitoramento", autocommit=False,
        )
        with self.conn.cursor() as cur:
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            cur.execute(f"SET statement_timeout = '{int(s.db_statement_timeout_s)}s'")
            # Zabbix 8.0 levou o estado das triggers (value) para trigger_rtdata
            cur.execute("SELECT to_regclass('trigger_rtdata') IS NOT NULL")
            self._trigger_rtdata = cur.fetchone()[0]
        self.conn.commit()
        self._n = 0

    def close(self) -> None:
        try:
            self.conn.rollback()
        finally:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ util
    def _stream(self, sql: str, params: Sequence = ()) -> Iterator[tuple]:
        self._n += 1
        with self.conn.cursor(name=f"cat_{self._n}") as cur:
            cur.itersize = 20000
            cur.execute(sql, params)
            yield from cur

    def _all(self, sql: str, params: Sequence = ()) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # ----------------------------------------------------------------- dados
    def version(self) -> str:
        try:
            row = self._all("SELECT mandatory FROM dbversion")
            return str(row[0][0]) if row else ""
        except psycopg.Error:
            self.conn.rollback()
            return ""

    def hosts(self) -> Iterator[tuple]:
        """hostid, host, name, status, maintenance_status, flags, proxy, description"""
        return self._stream(f"""
            SELECT h.hostid, h.host, h.name, h.status, h.maintenance_status, h.flags,
                   COALESCE(p.name, 'grupo ' || pg.name, ''), COALESCE(h.description, '')
              FROM hosts h
              LEFT JOIN proxy p ON p.proxyid = h.proxyid
              LEFT JOIN proxy_group pg ON pg.proxy_groupid = h.proxy_groupid
             WHERE h.status IN (0, 1) AND h.flags IN {_REAL}
        """)

    def groups(self) -> Iterator[tuple]:
        """groupid, name  (somente host groups; template groups ficam de fora)"""
        return self._stream("SELECT groupid, name FROM hstgrp WHERE type = 0")

    def host_groups(self) -> Iterator[tuple]:
        return self._stream("SELECT hostid, groupid FROM hosts_groups")

    def host_templates(self) -> Iterator[tuple]:
        """hostid, templateid, nome do template (apenas vínculo direto)"""
        return self._stream("""
            SELECT ht.hostid, ht.templateid, t.name
              FROM hosts_templates ht
              JOIN hosts t ON t.hostid = ht.templateid
              JOIN hosts h ON h.hostid = ht.hostid
             WHERE h.status IN (0, 1)
        """)

    def host_tags(self) -> Iterator[tuple]:
        return self._stream("SELECT hostid, tag, value FROM host_tag")

    def host_macros(self) -> Iterator[tuple]:
        """Somente macros do tipo texto (type 0). Secretas e de vault nunca são lidas.

        Se o usuário não tiver permissão em hostmacro, segue sem macros.
        """
        try:
            return iter(list(self._stream("SELECT hostid, macro, value FROM hostmacro WHERE type = 0")))
        except psycopg.errors.InsufficientPrivilege:
            self.conn.rollback()
            log.warning("sem permissão em hostmacro: regras por macro serão ignoradas")
            return iter(())

    def interfaces(self) -> Iterator[tuple]:
        """hostid, type, ip, dns, port, available (interface principal de cada tipo)"""
        return self._stream("""
            SELECT hostid, type, ip, dns, port, available
              FROM interface
             WHERE main = 1
        """)

    def item_types(self) -> Iterator[tuple]:
        """hostid, type, status, total, unsupported"""
        return self._stream(f"""
            SELECT i.hostid, i.type, i.status, COUNT(*),
                   COUNT(*) FILTER (WHERE rt.state = 1)
              FROM items i
              JOIN hosts h ON h.hostid = i.hostid AND h.status IN (0, 1)
              LEFT JOIN item_rtdata rt ON rt.itemid = i.itemid
             WHERE i.flags IN {_REAL}
             GROUP BY i.hostid, i.type, i.status
        """)

    def item_families(self) -> Iterator[tuple]:
        """hostid, chave base (antes do '['), total, exemplo de nome"""
        return self._stream(f"""
            SELECT i.hostid, split_part(i.key_, '[', 1), COUNT(*), MIN(i.name)
              FROM items i
              JOIN hosts h ON h.hostid = i.hostid AND h.status IN (0, 1)
             WHERE i.flags IN {_REAL}
             GROUP BY 1, 2
        """)

    def item_tags(self) -> Iterator[tuple]:
        """hostid, tag, value, total de itens"""
        return self._stream(f"""
            SELECT i.hostid, it.tag, it.value, COUNT(*)
              FROM item_tag it
              JOIN items i ON i.itemid = it.itemid AND i.flags IN {_REAL}
              JOIN hosts h ON h.hostid = i.hostid AND h.status IN (0, 1)
             GROUP BY 1, 2, 3
        """)

    def triggers(self) -> Iterator[tuple]:
        """triggerid, hostid, descrição, prioridade, status, value (1 = em problema)"""
        if self._trigger_rtdata:
            value, rtdata, group = "COALESCE(r.value, 0)", "LEFT JOIN trigger_rtdata r ON r.triggerid = t.triggerid", ", r.value"
        else:
            value, rtdata, group = "t.value", "", ""
        return self._stream(f"""
            SELECT t.triggerid, i.hostid, t.description, t.priority, t.status, {value}
              FROM triggers t
              {rtdata}
              JOIN functions f ON f.triggerid = t.triggerid
              JOIN items i     ON i.itemid = f.itemid
              JOIN hosts h     ON h.hostid = i.hostid AND h.status IN (0, 1)
             WHERE t.flags IN {_REAL}
             GROUP BY t.triggerid, i.hostid{group}
        """)

    # ------------------------------------------------- regras sobre os itens
    @staticmethod
    def _item_where(keys: list[str], names: list[str]) -> tuple[str, list[str]]:
        parts, params = [], []
        for k in keys:
            parts.append("i.key_ ~* %s")
            params.append(k)
        for n in names:
            parts.append("i.name ~* %s")
            params.append(n)
        return " OR ".join(parts), params

    def match_items(self, keys: list[str], names: list[str]) -> tuple[list[tuple], set[int]]:
        """Avalia regras de item no próprio PostgreSQL.

        Retorna (famílias encontradas: hostid, chave base, total, exemplo) e o
        conjunto de triggers que usam algum desses itens.
        """
        where, params = self._item_where(keys, names)
        if not where:
            return [], set()
        fams = list(self._stream(f"""
            SELECT i.hostid, split_part(i.key_, '[', 1), COUNT(*), MIN(i.name)
              FROM items i
              JOIN hosts h ON h.hostid = i.hostid AND h.status IN (0, 1)
             WHERE i.flags IN {_REAL} AND ({where})
             GROUP BY 1, 2
        """, params))
        trig = {r[0] for r in self._stream(f"""
            SELECT DISTINCT f.triggerid
              FROM functions f
              JOIN items i ON i.itemid = f.itemid
             WHERE i.flags IN {_REAL} AND ({where})
        """, params)}
        return fams, trig
