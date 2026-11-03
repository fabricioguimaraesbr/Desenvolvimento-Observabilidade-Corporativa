"""Leitura e validação do arquivo de regras (config/rules.yaml).

As regras definem o que pertence a cada aplicação. Há duas fontes:

1. Aplicações automáticas: cada host group que passa pelos filtros
   `auto_applications` vira uma aplicação.
2. Aplicações declaradas em `applications`: regras extras por nome de host,
   tags, macros, templates, chaves/nomes de itens e nomes de triggers.

Uma aplicação declarada com o mesmo nome de uma automática é mesclada a ela
(as regras se somam e os metadados — dono, descrição — são aplicados).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "app"


def _compile_list(values: Any, where: str) -> list[re.Pattern]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out = []
    for v in values:
        try:
            out.append(re.compile(str(v)))
        except re.error as exc:
            raise ValueError(f"Regex inválida em {where}: {v!r} ({exc})") from exc
    return out


def _compile_pairs(values: Any, where: str) -> list[tuple[re.Pattern, re.Pattern]]:
    """Aceita {tag: valor_regex} ou [{tag: regex, value: regex}]."""
    if not values:
        return []
    pairs: list[tuple[Any, Any]] = []
    if isinstance(values, dict):
        pairs = list(values.items())
    else:
        for entry in values:
            pairs.append((entry.get("tag") or entry.get("macro") or entry.get("name"), entry.get("value", ".*")))
    out = []
    for k, v in pairs:
        try:
            out.append((re.compile(f"^{re.escape(str(k))}$" if not str(k).startswith("^") else str(k)),
                        re.compile(str(v if v is not None else ".*"))))
        except re.error as exc:
            raise ValueError(f"Regex inválida em {where}: {k!r}={v!r} ({exc})") from exc
    return out


def _str_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    return [str(v) for v in values]


@dataclass
class AppRule:
    name: str
    description: str = ""
    owner: str = ""
    contact: str = ""
    host_groups: list[re.Pattern] = field(default_factory=list)
    host_names: list[re.Pattern] = field(default_factory=list)
    host_tags: list[tuple[re.Pattern, re.Pattern]] = field(default_factory=list)
    host_macros: list[tuple[re.Pattern, re.Pattern]] = field(default_factory=list)
    templates: list[re.Pattern] = field(default_factory=list)
    # Regras avaliadas no PostgreSQL (sintaxe de regex POSIX, sem diferenciar maiúsculas)
    item_keys: list[str] = field(default_factory=list)
    item_names: list[str] = field(default_factory=list)
    # Regras avaliadas em Python sobre o nome das triggers
    triggers: list[re.Pattern] = field(default_factory=list)
    # "items": o host entra só com os itens/triggers encontrados (escopo parcial)
    # "host":  o host entra inteiro na aplicação
    partial_scope: str = "items"

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def has_item_rules(self) -> bool:
        return bool(self.item_keys or self.item_names)


@dataclass
class AutoConfig:
    enabled: bool = True
    include: list[re.Pattern] = field(default_factory=lambda: [re.compile(".*")])
    exclude: list[re.Pattern] = field(default_factory=list)
    name_pattern: re.Pattern | None = None

    def app_name_for_group(self, group: str) -> str | None:
        if not self.enabled:
            return None
        if not any(p.search(group) for p in self.include):
            return None
        if any(p.search(group) for p in self.exclude):
            return None
        if self.name_pattern:
            m = self.name_pattern.search(group)
            if not m:
                return None
            name = m.groupdict().get("app") or (m.group(1) if m.groups() else m.group(0))
            return name.strip() or None
        return group


@dataclass
class Rules:
    auto: AutoConfig
    apps: list[AppRule]
    hidden_apps: list[re.Pattern] = field(default_factory=list)


def load_rules(path: Path) -> Rules:
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    auto_raw = data.get("auto_applications", {}) or {}
    name_pattern = auto_raw.get("name_pattern")
    auto = AutoConfig(
        enabled=bool(auto_raw.get("enabled", True)),
        include=_compile_list(auto_raw.get("include", [".*"]), "auto_applications.include"),
        exclude=_compile_list(auto_raw.get("exclude", []), "auto_applications.exclude"),
        name_pattern=re.compile(name_pattern) if name_pattern else None,
    )

    apps: list[AppRule] = []
    for i, raw in enumerate(data.get("applications", []) or []):
        where = f"applications[{i}]"
        if not raw.get("name"):
            raise ValueError(f"{where}: campo 'name' é obrigatório")
        m = raw.get("match", {}) or {}
        scope = str(raw.get("partial_scope", "items")).lower()
        if scope not in {"items", "host"}:
            raise ValueError(f"{where}.partial_scope deve ser 'items' ou 'host'")
        apps.append(AppRule(
            name=str(raw["name"]).strip(),
            description=str(raw.get("description", "") or ""),
            owner=str(raw.get("owner", "") or ""),
            contact=str(raw.get("contact", "") or ""),
            host_groups=_compile_list(m.get("host_groups"), f"{where}.match.host_groups"),
            host_names=_compile_list(m.get("host_names"), f"{where}.match.host_names"),
            host_tags=_compile_pairs(m.get("host_tags"), f"{where}.match.host_tags"),
            host_macros=_compile_pairs(m.get("host_macros"), f"{where}.match.host_macros"),
            templates=_compile_list(m.get("templates"), f"{where}.match.templates"),
            item_keys=_str_list(m.get("item_keys")),
            item_names=_str_list(m.get("item_names")),
            triggers=_compile_list(m.get("triggers"), f"{where}.match.triggers"),
            partial_scope=scope,
        ))

    return Rules(auto=auto, apps=apps,
                 hidden_apps=_compile_list(data.get("hidden_applications"), "hidden_applications"))
