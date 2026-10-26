/* Catálogo de Monitoramento — interface (sem dependências externas). */
(() => {
  "use strict";

  const $main = document.getElementById("main");
  const nf = new Intl.NumberFormat("pt-BR");
  const n = (v) => nf.format(v || 0);
  const SEV = ["Não classificada", "Informação", "Atenção", "Média", "Alta", "Desastre"];
  let CONFIG = { zabbix_url: "", title: "Catálogo de Monitoramento" };

  // ----------------------------------------------------------- utilidades
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;
  const html = (strings, ...vals) => strings.reduce((acc, s, i) => acc + s + (i < vals.length ? vals[i] : ""), "");

  async function api(path) {
    const r = await fetch(path, { headers: { Accept: "application/json" } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(body.detail || `Erro ${r.status}`); e.status = r.status; e.body = body; throw e; }
    return body;
  }

  function debounce(fn, ms = 250) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function sevbar(counts, wide = false) {
    const total = counts.reduce((a, b) => a + b, 0);
    if (!total) return `<div class="sevbar${wide ? " sevbar--wide" : ""}" aria-label="Sem triggers"></div>`;
    const label = counts.map((c, i) => c ? `${SEV[i]}: ${n(c)}` : "").filter(Boolean).join(", ");
    const parts = counts.map((c, i) => c ? `<span class="s${i}" style="width:${(c / total) * 100}%"></span>` : "").join("");
    return `<div class="sevbar${wide ? " sevbar--wide" : ""}" role="img" aria-label="${esc(label)}" title="${esc(label)}">${parts}</div>`;
  }

  function legend(counts, active = null, clickable = false) {
    return `<ul class="legend">${counts.map((c, i) => {
      const inner = `<i class="s${i}"></i>${SEV[i]} <b>${n(c)}</b>`;
      return `<li>${clickable ? `<button type="button" data-sev="${i}" aria-pressed="${active === i}">${inner}</button>` : inner}</li>`;
    }).reverse().join("")}</ul>`;
  }

  function bars(rows, labelKey, valKey, max = 12) {
    if (!rows.length) return `<p class="sub">Sem dados.</p>`;
    const top = Math.max(...rows.map((r) => r[valKey] || 0)) || 1;
    return `<ul class="bars">${rows.slice(0, max).map((r) => html`
      <li><span class="label" title="${esc(r[labelKey])}">${esc(r[labelKey])}</span><span class="val">${n(r[valKey])}</span>
      <span class="track"><span class="fill" style="width:${((r[valKey] || 0) / top) * 100}%"></span></span></li>`).join("")}</ul>`;
  }

  function hostStatus(h) {
    if (h.status === 1) return `<span class="pill pill--off">Desativado</span>`;
    if (h.maintenance) return `<span class="pill pill--off">Em manutenção</span>`;
    if (h.available === 2) return `<span class="pill pill--bad">Indisponível</span>`;
    if (h.available === 1) return `<span class="pill pill--ok">Disponível</span>`;
    return `<span class="pill pill--off">Sem interface ativa</span>`;
  }

  const zbx = {
    latest: (id) => CONFIG.zabbix_url && `${CONFIG.zabbix_url}/zabbix.php?action=latest.view&hostids%5B%5D=${id}&filter_set=1`,
    problems: (id) => CONFIG.zabbix_url && `${CONFIG.zabbix_url}/zabbix.php?action=problem.view&hostids%5B%5D=${id}&filter_set=1`,
  };

  function setNav(route) {
    document.querySelectorAll(".nav a").forEach((a) => {
      const href = a.getAttribute("href");
      const on = (href === "#/" && (route === "" || route.startsWith("app"))) || (href !== "#/" && route.startsWith(href.slice(2)));
      on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
    });
    document.body.classList.toggle("home", route === "" || route.startsWith("busca"));
  }

  function errorView(e) {
    if (e.status === 503) {
      const c = e.body?.collector || {};
      return html`<div class="wrap empty"><strong>O catálogo ainda está sendo montado</strong>
        ${c.running ? "A primeira coleta está em andamento. Atualize a página em alguns minutos." :
          `A última coleta falhou${c.last_error ? `: <code>${esc(c.last_error)}</code>` : "."} Verifique os logs do container e as credenciais do banco.`}</div>`;
    }
    if (e.status === 404) return `<div class="wrap empty"><strong>Não encontrado</strong>Esse item não existe no catálogo atual. Ele pode ter sido removido do Zabbix ou renomeado. <a href="#/">Voltar às aplicações</a></div>`;
    return `<div class="wrap empty"><strong>Não foi possível carregar</strong>${esc(e.message)}</div>`;
  }

  // -------------------------------------------------------------- início
  async function viewHome() {
    const [sum, apps] = await Promise.all([api("/api/summary"), api("/api/apps")]);
    const m = sum.meta;
    const sevCounts = [0, 1, 2, 3, 4, 5].map((i) => (sum.severities.find((s) => s.priority === i) || {}).n || 0);
    let sort = "name";
    let list = apps;

    $main.innerHTML = html`
      <section class="band">
        <div class="wrap">
          <h1 class="display">O que monitoramos?</h1>
          <form class="hero-search" role="search" data-search-form>
            <label class="sr" for="heroq">Buscar no catálogo</label>
            <input id="heroq" name="q" type="search" autocomplete="off" autofocus
              placeholder="Aplicação, host, IP, template, chave de item ou trigger">
            <button type="submit">Buscar</button>
          </form>
          <p class="hero-hint">Experimente: ${["checkout", "pgsql", "certificate", "10.10."].map((x) => `<button type="button" data-try="${esc(x)}">${esc(x)}</button>`).join(", ")}</p>
          <dl class="figures">
            <div class="figure"><dt>aplicações</dt><dd>${n(m.apps)}</dd></div>
            <div class="figure"><dt>hosts</dt><dd>${n(m.hosts)}</dd></div>
            <div class="figure"><dt>itens monitorados</dt><dd>${n(m.items)}</dd></div>
            <div class="figure"><dt>triggers</dt><dd>${n(m.triggers)}</dd></div>
            <div class="figure"><dt>em problema agora</dt><dd>${n(sum.problems)}</dd></div>
          </dl>
        </div>
      </section>

      <section class="section">
        <div class="wrap">
          <div class="section__head">
            <div>
              <h2 class="h2">Aplicações</h2>
              <p class="sub">Cada aplicação reúne os hosts do seu host group e o que as regras do catálogo associam a ela.</p>
            </div>
            <div class="tools">
              <label class="sr" for="appq">Filtrar aplicações</label>
              <input class="field" id="appq" type="search" placeholder="Filtrar por nome ou responsável">
              <a class="btn" href="/api/export/apps.xlsx">Exportar Excel</a>
              <a class="btn" href="/api/export/apps.csv">CSV</a>
            </div>
          </div>
          <div class="table-scroll"><table class="table" id="apps"></table></div>
        </div>
      </section>

      <section class="section">
        <div class="wrap grid2">
          <div><h3 class="h3">Triggers ativas por severidade</h3>${sevbar(sevCounts, true)}${legend(sevCounts)}</div>
          <div><h3 class="h3">Itens por tipo de coleta</h3>${bars(sum.item_types, "label", "n", 8)}</div>
          <div><h3 class="h3">Hosts por proxy</h3>${bars(sum.proxies, "proxy", "n", 8)}</div>
          <div><h3 class="h3">Saúde da configuração</h3>
            <dl class="kv">
              <dt>Hosts indisponíveis</dt><dd>${n(m.hosts_unavailable)}</dd>
              <dt>Itens não suportados</dt><dd>${n(sum.items_unsupported)}</dd>
              <dt>Hosts sem aplicação</dt><dd><a href="#/sem-aplicacao">${n(m.hosts_unmapped)}</a></dd>
              <dt>Coleta</dt><dd>${esc(fmtDate(m.collected_at))}, levou ${esc(m.duration_s)} s</dd>
            </dl>
          </div>
        </div>
      </section>`;

    const cols = [
      ["name", "Aplicação", ""], ["hosts", "Hosts", "n"], ["items", "Itens", "n"], ["triggers", "Triggers", "n hide-s"],
      ["sev", "Severidade das triggers", "hide-s"], ["problems", "Em problema", "n"], ["unavail", "Indisponíveis", "n hide-s"],
    ];
    const sorters = {
      name: (a, b) => a.name.localeCompare(b.name, "pt-BR"), hosts: (a, b) => b.hosts - a.hosts,
      items: (a, b) => b.items - a.items, triggers: (a, b) => b.triggers - a.triggers, problems: (a, b) => b.problems - a.problems,
      unavail: (a, b) => b.hosts_unavailable - a.hosts_unavailable,
    };
    const $t = document.getElementById("apps");
    function draw() {
      const rows = [...list].sort(sorters[sort]);
      $t.innerHTML = html`<thead><tr>${cols.map(([k, l, c]) => `<th class="${c}" scope="col">${sorters[k] ? `<button type="button" data-sort="${k}" aria-pressed="${sort === k}">${l}</button>` : l}</th>`).join("")}</tr></thead>
        <tbody>${rows.length ? rows.map((a) => html`<tr data-href="#/app/${enc(a.slug)}">
          <td class="name"><a href="#/app/${enc(a.slug)}">${esc(a.name)}</a>${a.owner ? `<small>${esc(a.owner)}</small>` : ""}</td>
          <td class="n">${n(a.hosts)}${a.hosts_partial ? `<small class="zero" title="Hosts compartilhados com outras aplicações"> +${n(a.hosts_partial)} parc.</small>` : ""}</td>
          <td class="n">${n(a.items)}</td>
          <td class="n hide-s">${n(a.triggers)}</td>
          <td class="hide-s">${sevbar([a.sev0, a.sev1, a.sev2, a.sev3, a.sev4, a.sev5])}</td>
          <td class="n">${a.problems ? `<span class="flag flag--problem">${n(a.problems)}</span>` : `<span class="zero">0</span>`}</td>
          <td class="n hide-s">${a.hosts_unavailable ? `<span class="flag flag--warn">${n(a.hosts_unavailable)}</span>` : `<span class="zero">0</span>`}</td>
        </tr>`).join("") : `<tr><td colspan="7" class="zero">Nenhuma aplicação com esse nome. Tente a busca geral, que também procura em hosts, itens e triggers.</td></tr>`}</tbody>`;
    }
    draw();
    $t.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-sort]");
      if (b) { sort = b.dataset.sort; draw(); return; }
      const tr = ev.target.closest("tr[data-href]");
      if (tr && !ev.target.closest("a")) location.hash = tr.dataset.href;
    });
    document.getElementById("appq").addEventListener("input", (ev) => {
      const q = ev.target.value.trim().toLocaleLowerCase("pt-BR");
      list = apps.filter((a) => (a.name + " " + (a.owner || "")).toLocaleLowerCase("pt-BR").includes(q));
      draw();
    });
    $main.querySelectorAll("[data-try]").forEach((b) => b.addEventListener("click", () => { location.hash = `#/busca?q=${enc(b.dataset.try)}`; }));
  }

  // ----------------------------------------------------------- aplicação
  const APP_TABS = [["", "Visão geral"], ["hosts", "Hosts"], ["itens", "Itens"], ["triggers", "Triggers"], ["templates", "Templates"]];

  async function viewApp(slug, tab = "") {
    const a = await api(`/api/apps/${enc(slug)}`);
    document.title = `${a.name} · ${CONFIG.title}`;
    const counts = { hosts: a.hosts, itens: a.items, triggers: a.triggers, templates: a.templates.length };
    $main.innerHTML = html`
      <section class="band">
        <div class="wrap">
          <p class="band__crumb"><a href="#/">Aplicações</a></p>
          <h1 class="display display--m">${esc(a.name)}</h1>
          ${a.description ? `<p class="band__lead">${esc(a.description)}</p>` : ""}
          <div class="band__meta">
            ${a.owner ? `<span>Responsável <b>${esc(a.owner)}</b></span>` : ""}
            ${a.contact ? `<span>Contato <b>${esc(a.contact)}</b></span>` : ""}
            <span>Origem <b>${esc(a.source)}</b></span>
          </div>
          <dl class="figures">
            <div class="figure"><dt>hosts</dt><dd>${n(a.hosts)}</dd></div>
            <div class="figure"><dt>itens ativos</dt><dd>${n(a.items)}</dd></div>
            <div class="figure"><dt>triggers</dt><dd>${n(a.triggers)}</dd></div>
            <div class="figure"><dt>em problema</dt><dd>${n(a.problems)}</dd></div>
            <div class="figure"><dt>indisponíveis</dt><dd>${n(a.hosts_unavailable)}</dd></div>
            <div class="tools" style="align-self:end">
              <a class="btn btn--band" href="/api/export/apps/${enc(slug)}.xlsx">Exportar Excel</a>
              <a class="btn btn--band" href="/api/export/apps/${enc(slug)}.csv">CSV dos hosts</a>
            </div>
          </dl>
        </div>
      </section>
      <div class="tabs"><div class="wrap tabs__inner" role="tablist" aria-label="Seções da aplicação">
        ${APP_TABS.map(([k, l]) => `<a class="tab" role="tab" href="#/app/${enc(slug)}${k ? "/" + k : ""}" aria-selected="${tab === k}">${l}${counts[k] != null ? `<small>${n(counts[k])}</small>` : ""}</a>`).join("")}
      </div></div>
      <section class="section"><div class="wrap" id="tab"></div></section>`;
    const $tab = document.getElementById("tab");
    const fn = { "": tabOverview, hosts: tabHosts, itens: tabItems, triggers: tabTriggers, templates: tabTemplates }[tab] || tabOverview;
    await fn($tab, a, slug);
  }

  function tabOverview($el, a) {
    const counts = a.severities.map((s) => s.n);
    $el.innerHTML = html`
      ${a.hosts_partial ? `<p class="notice">${n(a.hosts_partial)} hosts são compartilhados com outras aplicações. Deles, só entram aqui os itens e triggers que citam ${esc(a.name)}.</p>` : ""}
      <div class="grid2">
        <div><h3 class="h3">Triggers ativas por severidade</h3>${sevbar(counts, true)}${legend(counts)}</div>
        <div><h3 class="h3">Itens por tipo de coleta</h3>${bars(a.item_types, "label", "n", 10)}</div>
        <div><h3 class="h3">Hosts por proxy</h3>${bars(a.proxies, "proxy", "n", 8)}</div>
        <div><h3 class="h3">Como os hosts foram associados</h3>${bars(a.matched_by, "matched_by", "n", 8)}</div>
        <div style="grid-column:1/-1"><h3 class="h3">Tags dos hosts</h3>
          ${a.tags.length ? `<div class="chips">${a.tags.map((t) => `<span class="chip">${esc(t.tag)}${t.value ? `: ${esc(t.value)}` : ""} <b>${n(t.hosts)}</b></span>`).join("")}</div>` : `<p class="sub">Os hosts desta aplicação não têm tags.</p>`}
        </div>
      </div>`;
  }

  async function tabHosts($el, a, slug) {
    let page = 1, q = "", status = "";
    $el.innerHTML = html`
      <div class="section__head">
        <div><h2 class="h2">Hosts</h2><p class="sub">Clique em um host para ver grupos, templates, itens e triggers.</p></div>
        <div class="tools">
          <label class="sr" for="hq">Filtrar hosts</label>
          <input class="field" id="hq" type="search" placeholder="Nome, host técnico ou IP">
          <label class="sr" for="hs">Situação</label>
          <select class="field" id="hs">
            <option value="">Todas as situações</option><option value="unavailable">Indisponíveis</option>
            <option value="disabled">Desativados</option><option value="maintenance">Em manutenção</option>
            <option value="partial">Compartilhados (parcial)</option>
          </select>
        </div>
      </div>
      <div class="table-scroll"><table class="table" id="ht"></table></div><div class="pager" id="hp"></div>`;
    const $t = document.getElementById("ht"), $p = document.getElementById("hp");
    async function load() {
      const d = await api(`/api/apps/${enc(slug)}/hosts?q=${enc(q)}&status=${enc(status)}&page=${page}&size=50`);
      $t.innerHTML = html`<thead><tr><th>Host</th><th class="hide-s">IP / DNS</th><th>Situação</th><th class="n">Itens</th><th class="n">Triggers</th><th class="n hide-s">Em problema</th><th class="hide-s">Proxy</th></tr></thead>
        <tbody>${d.rows.length ? d.rows.map((h) => html`<tr data-href="#/host/${h.hostid}">
          <td class="name"><a href="#/host/${h.hostid}">${esc(h.name)}</a>${h.name !== h.host ? `<small>${esc(h.host)}</small>` : ""}${h.scope === "partial" ? ` <span class="pill pill--part" title="Associado por ${esc(h.matched_by)}">parcial</span>` : ""}</td>
          <td class="hide-s"><span class="mono">${esc(h.ip || "")}</span><small class="zero" style="display:block">${esc(h.dns || "")}</small></td>
          <td>${hostStatus(h)}</td>
          <td class="n">${n(h.items)}</td><td class="n">${n(h.triggers)}</td>
          <td class="n hide-s">${h.triggers_problem ? `<span class="flag flag--problem">${n(h.triggers_problem)}</span>` : `<span class="zero">0</span>`}</td>
          <td class="hide-s">${esc(h.proxy || "Servidor")}</td></tr>`).join("") : `<tr><td colspan="7" class="zero">Nenhum host com esse filtro.</td></tr>`}</tbody>`;
      pager($p, d, (p) => { page = p; load(); });
    }
    $t.addEventListener("click", rowLink);
    document.getElementById("hq").addEventListener("input", debounce((ev) => { q = ev.target.value; page = 1; load(); }));
    document.getElementById("hs").addEventListener("change", (ev) => { status = ev.target.value; page = 1; load(); });
    await load();
  }

  async function tabItems($el, a, slug) {
    $el.innerHTML = html`
      <div class="section__head">
        <div><h2 class="h2">Itens por chave</h2>
          <p class="sub">Itens agrupados pela chave sem parâmetros. Por exemplo, todos os <code>vfs.fs.size[…]</code> aparecem numa linha só.</p></div>
        <div class="tools"><label class="sr" for="iq">Filtrar itens</label><input class="field" id="iq" type="search" placeholder="Chave ou nome do item"></div>
      </div>
      <div class="grid2" style="grid-template-columns:minmax(0,2fr) minmax(260px,1fr)">
        <div class="table-scroll"><table class="table" id="it"></table></div>
        <div id="itags"></div>
      </div>`;
    const $t = document.getElementById("it");
    async function load(q = "") {
      const d = await api(`/api/apps/${enc(slug)}/items?q=${enc(q)}`);
      $t.innerHTML = html`<thead><tr><th>Chave</th><th class="n">Itens</th><th class="n">Hosts</th></tr></thead>
        <tbody>${d.families.length ? d.families.map((f) => html`<tr>
          <td class="name"><span class="mono">${esc(f.key_base)}</span><small>${esc(f.sample_name)}</small></td>
          <td class="n">${n(f.items)}</td><td class="n">${n(f.hosts)}</td></tr>`).join("") : `<tr><td colspan="3" class="zero">Nenhum item com esse filtro.</td></tr>`}</tbody>`;
      if (!q) document.getElementById("itags").innerHTML = `<h3 class="h3">Tags dos itens</h3>${bars(d.item_tags.map((t) => ({ l: t.value ? `${t.tag}: ${t.value}` : t.tag, n: t.items })), "l", "n", 20)}`;
    }
    document.getElementById("iq").addEventListener("input", debounce((ev) => load(ev.target.value)));
    await load();
  }

  async function tabTriggers($el, a, slug) {
    let page = 1, q = "", sev = null, problems = false;
    const counts = a.severities.map((s) => s.n);
    $el.innerHTML = html`
      <div class="section__head">
        <div><h2 class="h2">Triggers</h2><p class="sub">Triggers com o mesmo nome aparecem juntas, com o número de hosts que as têm.</p></div>
        <div class="tools">
          <label class="sr" for="tq">Filtrar triggers</label>
          <input class="field" id="tq" type="search" placeholder="Nome da trigger">
          <label class="btn"><input type="checkbox" id="tp"> Só em problema</label>
        </div>
      </div>
      <div id="tl"></div>
      <div class="table-scroll" style="margin-top:18px"><table class="table" id="tt"></table></div><div class="pager" id="tpg"></div>`;
    const $t = document.getElementById("tt"), $p = document.getElementById("tpg"), $l = document.getElementById("tl");
    const drawLegend = () => { $l.innerHTML = legend(counts, sev, true); };
    async function load() {
      const d = await api(`/api/apps/${enc(slug)}/triggers?q=${enc(q)}&page=${page}&size=50${sev != null ? `&severity=${sev}` : ""}${problems ? "&problems=true" : ""}`);
      $t.innerHTML = html`<thead><tr><th>Trigger</th><th>Severidade</th><th class="n">Hosts</th><th class="n">Em problema</th><th class="n hide-s">Desativadas</th></tr></thead>
        <tbody>${d.rows.length ? d.rows.map((t) => html`<tr>
          <td>${esc(t.description)}</td><td style="white-space:nowrap"><i class="dot s${t.priority}"></i>${esc(t.severity)}</td>
          <td class="n">${n(t.hosts)}</td><td class="n">${t.problems ? `<span class="flag flag--problem">${n(t.problems)}</span>` : `<span class="zero">0</span>`}</td>
          <td class="n hide-s">${t.disabled ? n(t.disabled) : `<span class="zero">0</span>`}</td></tr>`).join("") : `<tr><td colspan="5" class="zero">Nenhuma trigger com esse filtro.</td></tr>`}</tbody>`;
      pager($p, { ...d, total: d.groups }, (p) => { page = p; load(); }, `${n(d.total)} triggers em ${n(d.groups)} nomes`);
    }
    drawLegend();
    $l.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-sev]"); if (!b) return;
      const v = Number(b.dataset.sev); sev = sev === v ? null : v; page = 1; drawLegend(); load();
    });
    document.getElementById("tq").addEventListener("input", debounce((ev) => { q = ev.target.value; page = 1; load(); }));
    document.getElementById("tp").addEventListener("change", (ev) => { problems = ev.target.checked; page = 1; load(); });
    await load();
  }

  function tabTemplates($el, a) {
    $el.innerHTML = html`
      <div class="section__head"><div><h2 class="h2">Templates</h2><p class="sub">Templates vinculados diretamente aos hosts da aplicação.</p></div></div>
      ${a.templates.length ? `<table class="table"><thead><tr><th>Template</th><th class="n">Hosts</th></tr></thead><tbody>
        ${a.templates.map((t) => `<tr><td><a href="#/busca?q=${enc(t.name)}">${esc(t.name)}</a></td><td class="n">${n(t.hosts)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="sub">Nenhum template vinculado diretamente.</p>`}`;
  }

  function pager($p, d, go, label) {
    const pages = Math.max(1, Math.ceil(d.total / d.size));
    $p.innerHTML = html`<span>${label || `${n(d.total)} resultados`}</span>
      <button class="btn" type="button" data-p="${d.page - 1}" ${d.page <= 1 ? "disabled" : ""}>Anterior</button>
      <span>Página ${n(d.page)} de ${n(pages)}</span>
      <button class="btn" type="button" data-p="${d.page + 1}" ${d.page >= pages ? "disabled" : ""}>Próxima</button>`;
    $p.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => go(Number(b.dataset.p))));
  }

  function rowLink(ev) {
    const tr = ev.target.closest("tr[data-href]");
    if (tr && !ev.target.closest("a")) location.hash = tr.dataset.href;
  }

  // ------------------------------------------------------------------ host
  async function viewHost(id) {
    const h = await api(`/api/hosts/${enc(id)}`);
    document.title = `${h.name} · ${CONFIG.title}`;
    const sev = [0, 1, 2, 3, 4, 5].map((i) => h.triggers.filter((t) => t.priority === i && t.status === 0).length);
    const first = h.apps[0];
    $main.innerHTML = html`
      <section class="band">
        <div class="wrap">
          <p class="band__crumb">${first ? `<a href="#/app/${enc(first.slug)}/hosts">${esc(first.name)}</a>` : `<a href="#/sem-aplicacao">Hosts sem aplicação</a>`}</p>
          <h1 class="display display--m">${esc(h.name)}</h1>
          <div class="band__meta">
            ${h.name !== h.host ? `<span>Host <b>${esc(h.host)}</b></span>` : ""}
            ${h.ip ? `<span>IP <b>${esc(h.ip)}</b></span>` : ""}
            ${h.dns ? `<span>DNS <b>${esc(h.dns)}</b></span>` : ""}
            <span>Proxy <b>${esc(h.proxy || "Servidor")}</b></span>
          </div>
          <dl class="figures">
            <div class="figure"><dt>itens ativos</dt><dd>${n(h.items_enabled)}</dd></div>
            <div class="figure"><dt>não suportados</dt><dd>${n(h.items_unsupported)}</dd></div>
            <div class="figure"><dt>triggers</dt><dd>${n(h.triggers_total)}</dd></div>
            <div class="figure"><dt>em problema</dt><dd>${n(h.triggers_problem)}</dd></div>
            <div class="tools" style="align-self:end">
              ${CONFIG.zabbix_url ? `<a class="btn btn--band" href="${zbx.latest(h.hostid)}" target="_blank" rel="noopener">Dados recentes no Zabbix</a>
              <a class="btn btn--band" href="${zbx.problems(h.hostid)}" target="_blank" rel="noopener">Problemas no Zabbix</a>` : ""}
            </div>
          </dl>
        </div>
      </section>
      <section class="section"><div class="wrap grid2">
        <div><h3 class="h3">Situação</h3>
          <dl class="kv"><dt>Status</dt><dd>${hostStatus(h)}</dd>
            <dt>Interface principal</dt><dd>${esc(h.iface || "Nenhuma")} (${esc(h.availability)})</dd>
            <dt>Host groups</dt><dd>${h.groups.map(esc).join(", ") || "Nenhum"}</dd>
            ${h.description ? `<dt>Descrição</dt><dd>${esc(h.description)}</dd>` : ""}
          </dl></div>
        <div><h3 class="h3">Aplicações</h3>
          ${h.apps.length ? `<div class="chips">${h.apps.map((x) => `<a class="chip" href="#/app/${enc(x.slug)}">${esc(x.name)}${x.scope === "partial" ? " (parcial)" : ""}</a>`).join("")}</div>`
            : `<p class="sub">Este host não entrou em nenhuma aplicação. Coloque-o num host group de aplicação ou crie uma regra no catálogo.</p>`}
          <h3 class="h3" style="margin-top:22px">Templates</h3>
          ${h.templates.length ? `<div class="chips">${h.templates.map((t) => `<a class="chip" href="#/busca?q=${enc(t)}">${esc(t)}</a>`).join("")}</div>` : `<p class="sub">Nenhum template vinculado.</p>`}
          ${h.tags.length ? `<h3 class="h3" style="margin-top:22px">Tags</h3><div class="chips">${h.tags.map((t) => `<span class="chip">${esc(t.tag)}${t.value ? `: ${esc(t.value)}` : ""}</span>`).join("")}</div>` : ""}
        </div>
        <div><h3 class="h3">Itens por tipo de coleta</h3>${bars(h.item_types, "label", "n", 10)}</div>
        <div><h3 class="h3">Triggers ativas por severidade</h3>${sevbar(sev, true)}${legend(sev)}</div>
      </div></section>
      <section class="section"><div class="wrap grid2" style="grid-template-columns:minmax(0,1fr) minmax(0,1.3fr)">
        <div><h3 class="h3">Itens por chave</h3>
          <table class="table"><thead><tr><th>Chave</th><th class="n">Itens</th></tr></thead><tbody>
          ${h.families.map((f) => `<tr><td class="name"><span class="mono">${esc(f.key_base)}</span><small>${esc(f.sample_name)}</small></td><td class="n">${n(f.total)}</td></tr>`).join("") || `<tr><td colspan="2" class="zero">Sem itens.</td></tr>`}
          </tbody></table></div>
        <div><h3 class="h3">Triggers</h3>
          <table class="table"><thead><tr><th>Trigger</th><th>Severidade</th><th>Estado</th></tr></thead><tbody>
          ${h.triggers.map((t) => `<tr><td>${esc(t.description)}</td><td style="white-space:nowrap"><i class="dot s${t.priority}"></i>${esc(t.severity)}</td>
            <td>${t.status === 1 ? `<span class="pill pill--off">Desativada</span>` : t.value === 1 ? `<span class="pill pill--bad">Em problema</span>` : `<span class="pill pill--ok">OK</span>`}</td></tr>`).join("") || `<tr><td colspan="3" class="zero">Sem triggers.</td></tr>`}
          </tbody></table></div>
      </div></section>`;
  }

  // ----------------------------------------------------------------- busca
  async function viewSearch(q) {
    const d = await api(`/api/search?q=${enc(q)}`);
    document.getElementById("topq").value = q;
    document.title = `Busca: ${q} · ${CONFIG.title}`;
    const total = d.apps.length + d.hosts.length + d.templates.length + d.items.length + d.triggers.length;
    $main.innerHTML = html`
      <section class="band"><div class="wrap">
        <p class="band__crumb"><a href="#/">Aplicações</a></p>
        <h1 class="display display--m">${esc(q)}</h1>
        <form class="hero-search" role="search" data-search-form>
          <label class="sr" for="sq">Nova busca</label>
          <input id="sq" name="q" type="search" value="${esc(q)}" autocomplete="off"><button type="submit">Buscar</button>
        </form>
      </div></section>
      <section class="section"><div class="wrap results" id="res">
        ${q.length < 2 ? `<div class="empty"><strong>Digite pelo menos 2 caracteres</strong>A busca procura em aplicações, hosts, IPs, templates, chaves de item e triggers.</div>` :
          !total ? `<div class="empty"><strong>Nada encontrado para “${esc(q)}”</strong>Confira a grafia ou tente um trecho menor, como parte do nome do host ou da chave do item.</div>` : ""}
        ${d.apps.length ? html`<div><h2 class="h2">Aplicações</h2><table class="table" style="margin-top:12px"><thead><tr><th>Aplicação</th><th class="n">Hosts</th><th class="n">Itens</th></tr></thead><tbody>
          ${d.apps.map((a) => `<tr data-href="#/app/${enc(a.slug)}"><td class="name"><a href="#/app/${enc(a.slug)}">${esc(a.name)}</a></td><td class="n">${n(a.hosts)}</td><td class="n">${n(a.items)}</td></tr>`).join("")}</tbody></table></div>` : ""}
        ${d.hosts.length ? html`<div><h2 class="h2">Hosts</h2><table class="table" style="margin-top:12px"><thead><tr><th>Host</th><th class="hide-s">IP</th><th>Situação</th><th>Aplicações</th></tr></thead><tbody>
          ${d.hosts.map((h) => `<tr data-href="#/host/${h.hostid}"><td class="name"><a href="#/host/${h.hostid}">${esc(h.name)}</a>${h.name !== h.host ? `<small>${esc(h.host)}</small>` : ""}</td><td class="hide-s mono">${esc(h.ip)}</td><td>${hostStatus(h)}</td><td>${esc(h.apps || "Nenhuma")}</td></tr>`).join("")}</tbody></table></div>` : ""}
        ${d.templates.length ? html`<div><h2 class="h2">Templates</h2><p class="sub">Escolha um template para ver em quais aplicações ele é usado.</p><table class="table" style="margin-top:12px"><thead><tr><th>Template</th><th class="n">Hosts</th><th>Usado em</th></tr></thead><tbody>
          ${d.templates.map((t, i) => `<tr><td>${esc(t.name)}</td><td class="n">${n(t.hosts)}</td><td><button class="btn" type="button" data-tpl="${i}">Ver aplicações</button></td></tr>`).join("")}</tbody></table></div>` : ""}
        ${d.items.length ? html`<div><h2 class="h2">Chaves de item</h2><table class="table" style="margin-top:12px"><thead><tr><th>Chave</th><th class="n">Itens</th><th class="n">Hosts</th><th>Usado em</th></tr></thead><tbody>
          ${d.items.map((f, i) => `<tr><td class="name"><span class="mono">${esc(f.key_base)}</span><small>${esc(f.sample_name)}</small></td><td class="n">${n(f.items)}</td><td class="n">${n(f.hosts)}</td><td><button class="btn" type="button" data-key="${i}">Ver aplicações</button></td></tr>`).join("")}</tbody></table></div>` : ""}
        ${d.triggers.length ? html`<div><h2 class="h2">Triggers</h2><table class="table" style="margin-top:12px"><thead><tr><th>Trigger</th><th>Severidade</th><th class="n">Hosts</th><th class="n">Em problema</th></tr></thead><tbody>
          ${d.triggers.map((t) => `<tr><td>${esc(t.description)}</td><td style="white-space:nowrap"><i class="dot s${t.priority}"></i>${esc(t.severity)}</td><td class="n">${n(t.hosts)}</td><td class="n">${t.problems ? `<span class="flag flag--problem">${n(t.problems)}</span>` : `<span class="zero">0</span>`}</td></tr>`).join("")}</tbody></table></div>` : ""}
      </div></section>`;
    const $res = document.getElementById("res");
    $res.addEventListener("click", async (ev) => {
      rowLink(ev);
      const b = ev.target.closest("[data-tpl],[data-key]");
      if (!b) return;
      const rows = b.dataset.tpl != null ? await api(`/api/templates/apps?name=${enc(d.templates[b.dataset.tpl].name)}`)
        : await api(`/api/items/apps?key=${enc(d.items[b.dataset.key].key_base)}`);
      b.parentElement.innerHTML = rows.length ? `<div class="chips">${rows.map((r) => `<a class="chip" href="#/app/${enc(r.slug)}">${esc(r.name)} <b>${n(r.hosts)}</b></a>`).join("")}</div>` : `<span class="zero">Nenhuma aplicação</span>`;
    });
  }

  // ------------------------------------------------------- sem aplicação
  async function viewUnmapped() {
    let page = 1, q = "";
    document.title = `Hosts sem aplicação · ${CONFIG.title}`;
    $main.innerHTML = html`
      <section class="band"><div class="wrap">
        <p class="band__crumb"><a href="#/">Aplicações</a></p>
        <h1 class="display display--m">Hosts sem aplicação</h1>
        <p class="band__lead">Hosts monitorados que não caíram em nenhuma aplicação. Para incluí-los, coloque-os num host group de aplicação ou crie uma regra no arquivo de regras do catálogo.</p>
      </div></section>
      <section class="section"><div class="wrap">
        <div class="section__head"><div class="tools" style="margin-left:0"><label class="sr" for="uq">Filtrar</label><input class="field" id="uq" type="search" placeholder="Nome do host"></div></div>
        <div class="table-scroll"><table class="table" id="ut"></table></div><div class="pager" id="up"></div>
      </div></section>`;
    const $t = document.getElementById("ut"), $p = document.getElementById("up");
    async function load() {
      const d = await api(`/api/unmapped?q=${enc(q)}&page=${page}`);
      $t.innerHTML = html`<thead><tr><th>Host</th><th>Host groups</th><th>Situação</th><th class="n">Itens</th></tr></thead><tbody>
        ${d.rows.length ? d.rows.map((h) => `<tr data-href="#/host/${h.hostid}"><td class="name"><a href="#/host/${h.hostid}">${esc(h.name)}</a>${h.name !== h.host ? `<small>${esc(h.host)}</small>` : ""}</td><td>${esc(h.groups || "")}</td><td>${hostStatus(h)}</td><td class="n">${n(h.items)}</td></tr>`).join("")
          : `<tr><td colspan="4" class="zero">Todos os hosts estão em alguma aplicação.</td></tr>`}</tbody>`;
      pager($p, d, (p) => { page = p; load(); });
    }
    $t.addEventListener("click", rowLink);
    document.getElementById("uq").addEventListener("input", debounce((ev) => { q = ev.target.value; page = 1; load(); }));
    await load();
  }

  // ------------------------------------------------------------- sobre
  async function viewAbout() {
    const c = await api("/api/health");
    document.title = `Como funciona · ${CONFIG.title}`;
    $main.innerHTML = html`
      <section class="band"><div class="wrap">
        <p class="band__crumb"><a href="#/">Aplicações</a></p>
        <h1 class="display display--m">Como funciona</h1>
        <p class="band__lead">O catálogo é uma fotografia da configuração do Zabbix, refeita periodicamente. Ele não mostra valores coletados nem altera nada no Zabbix.</p>
      </div></section>
      <section class="section"><div class="wrap prose">
        <h3>De onde vêm os dados</h3>
        <p>Um coletor lê as tabelas de configuração do banco do Zabbix (hosts, grupos, templates, itens, triggers e tags) com um usuário somente leitura. O resultado é resumido e guardado num banco próprio, por isso as consultas aqui são rápidas mesmo com milhões de itens.</p>
        <h3>O que é uma aplicação</h3>
        <p>Por padrão, cada host group de aplicação vira uma aplicação. O time de observabilidade pode complementar isso com regras: nome do host, tags, macros, templates, chaves e nomes de itens ou nomes de triggers.</p>
        <p>Quando um host é compartilhado, como um servidor de banco usado por várias aplicações, ele pode entrar de forma <b>parcial</b>: só os itens e triggers que citam a aplicação contam para ela.</p>
        <h3>Atualização</h3>
        <p>Última coleta concluída: <b>${esc(fmtDate(c.collector.last_finished) || "nesta execução ainda não houve")}</b>.
          ${c.collector.next_run ? `Próxima: <b>${esc(fmtDate(c.collector.next_run))}</b>.` : ""}
          ${c.collector.running ? "Há uma coleta em andamento agora." : ""}
          ${c.collector.last_error ? `<br>Última falha: <code>${esc(c.collector.last_error)}</code>` : ""}</p>
        <h3>Precisa corrigir algo?</h3>
        <p>Se uma aplicação está faltando ou um host aparece no lugar errado, fale com o time de observabilidade e informe o nome da aplicação e dos hosts.</p>
      </div></section>`;
  }

  // ---------------------------------------------------------------- rotas
  async function route() {
    const hash = location.hash.replace(/^#\/?/, "");
    const [path, qs] = hash.split("?");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    const params = new URLSearchParams(qs || "");
    setNav(path);
    document.title = CONFIG.title;
    const prevApp = $main.dataset.app;
    if (!(parts[0] === "app" && prevApp === parts[1])) {
      $main.innerHTML = `<div class="wrap loading" role="status">Carregando…</div>`;
      window.scrollTo(0, 0);
    }
    $main.dataset.app = parts[0] === "app" ? parts[1] : "";
    try {
      if (!parts.length) await viewHome();
      else if (parts[0] === "app") await viewApp(parts[1], parts[2] || "");
      else if (parts[0] === "host") await viewHost(parts[1]);
      else if (parts[0] === "busca") await viewSearch(params.get("q") || "");
      else if (parts[0] === "sem-aplicacao") await viewUnmapped();
      else if (parts[0] === "sobre") await viewAbout();
      else throw Object.assign(new Error("Página não encontrada"), { status: 404 });
    } catch (e) {
      $main.dataset.app = "";
      $main.innerHTML = errorView(e);
    }
  }

  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest("[data-search-form]");
    if (!f) return;
    ev.preventDefault();
    const q = new FormData(f).get("q").toString().trim();
    if (q) location.hash = `#/busca?q=${enc(q)}`;
  });
  window.addEventListener("hashchange", route);

  api("/api/config").then((c) => {
    CONFIG = c;
    document.querySelector("[data-title]").textContent = c.title;
    const last = c.collector?.last_finished;
    document.querySelector("[data-collected]").textContent =
      (c.demo ? "Modo demonstração, dados fictícios. " : "") + (last ? `Atualizado em ${fmtDate(last)}` : "Aguardando a primeira coleta");
  }).catch(() => {}).finally(route);
})();
