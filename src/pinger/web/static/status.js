/* pinger — автообновление статусов через JSON.
 *
 * Элемент с data-status-url опрашивается раз в data-refresh-s секунд;
 * ответ — JSON, DOM обновляется точечно (без перерисовки и мигания).
 * Если состав строк/адресов/страниц изменился — полная перезагрузка
 * (структуру рисует сервер).
 */
(function () {
  "use strict";

  function setText(el, text) {
    if (el && el.textContent !== text) el.textContent = text;
  }

  function setStat(container, name, text, { pillClass } = {}) {
    var el = container.querySelector('[data-stat="' + name + '"]');
    if (!el) return;
    el.hidden = text === null;
    if (text !== null) setText(el, text);
    if (pillClass) {
      el.classList.remove("up", "down");
      if (pillClass) el.classList.add(pillClass);
    }
  }

  function renderSummary(container, stats) {
    setStat(container, "up", stats.up + " up", { pillClass: "up" });
    setStat(container, "down", stats.down ? stats.down + " down" : null,
            { pillClass: "down" });
    setStat(container, "no_data",
            stats.no_data ? stats.no_data + " без данных" : null);
    setStat(container, "total", "всего " + stats.total);
  }

  /* --- экран страницы -------------------------------------------------- */

  function renderPage(root, data) {
    // сводка
    var summary = root.querySelector('[data-role="summary"]');
    if (summary) renderSummary(summary, data.stats);

    var rows = root.querySelectorAll("tr[data-target-id]");
    var known = {};
    rows.forEach(function (tr) { known[tr.dataset.targetId] = tr; });

    var domChips = root.querySelectorAll("[data-address-id]");
    if (domChips.length !== countCells(data)) {
      window.location.reload();  // состав изменился — перерисует сервер
      return;
    }

    data.rows.forEach(function (row) {
      var tr = known[row.target_id];
      if (!tr) return;
      row.cells.forEach(function (cell) {
        var chip = tr.querySelector(
          '[data-address-id="' + cell.address_id + '"]');
        if (!chip) return;
        var state = cell.state || "unknown";
        chip.classList.remove("up", "down", "unknown");
        chip.classList.add(state);
        chip.classList.toggle("disabled", !cell.enabled);
        chip.title =
          (state === "up" ? "доступен"
            : state === "down" ? "недоступен" : "данных ещё нет")
          + (!cell.enabled ? " · выключен" : "");
        var up = chip.querySelector(".uptime");
        if (cell.uptime === null || cell.uptime === undefined) {
          if (up) up.remove();
        } else if (up) {
          setText(up, cell.uptime + "% · 24ч");
        } else {
          up = document.createElement("span");
          up.className = "uptime";
          up.title = "uptime за последние 24 ч";
          up.textContent = cell.uptime + "% · 24ч";
          chip.appendChild(up);
        }
      });
    });
  }

  function countCells(data) {
    return data.rows.reduce(function (n, r) { return n + r.cells.length; }, 0);
  }

  /* --- главный экран ---------------------------------------------------- */

  function renderIndex(root, data) {
    var cards = root.querySelectorAll("[data-page-id]");
    if (cards.length !== data.pages.length) {
      window.location.reload();
      return;
    }
    var byId = {};
    cards.forEach(function (c) { byId[c.dataset.pageId] = c; });

    data.pages.forEach(function (page) {
      var card = byId[page.id];
      if (!card) { window.location.reload(); return; }

      var off = card.querySelector('[data-role="off"]');
      if (off) off.hidden = !!page.enabled;

      var summary = card.querySelector('[data-role="summary"]');
      if (summary) renderSummary(summary, page);

      var ratio = card.querySelector('[data-role="ratio"]');
      if (ratio && page.total) {
        ["up", "down", "no_data"].forEach(function (part) {
          var seg = ratio.querySelector('[data-part="' + part + '"]');
          if (seg) seg.style.width = (page[part] * 100 / page.total) + "%";
        });
      }
    });
  }

  /* --- поллинг ------------------------------------------------------------ */

  function poll(root) {
    var url = root.dataset.statusUrl;
    var every = (parseInt(root.dataset.refreshS, 10) || 5) * 1000;
    var isIndex = url.indexOf("/index.json") !== -1;

    async function tick() {
      if (document.hidden) return;  // вкладка не видна — не дёргаем сервер
      try {
        var resp = await fetch(url, {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (resp.status === 401 || resp.status === 403) return;
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        var data = await resp.json();
        if (isIndex) renderIndex(root, data);
        else renderPage(root, data);
      } catch (e) {
        // сеть/сервер моргнули — тихо ждём следующего тика
      }
    }
    setInterval(tick, every);
  }

  function init() {
    document.querySelectorAll("[data-status-url]").forEach(poll);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
