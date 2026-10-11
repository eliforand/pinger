/* pinger — минимум JS: тосты ошибок HTMX и подтверждение опасных действий. */
(function () {
  function toast(message) {
    var old = document.getElementById("toast");
    if (old) old.remove();
    var el = document.createElement("div");
    el.id = "toast";
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 4000);
  }

  document.body.addEventListener("htmx:responseError", function (evt) {
    var code = evt.detail.xhr.status;
    if (code === 403) toast("Недостаточно прав для этого действия");
    else if (code === 400) toast("Ошибка запроса (возможно, устарела сессия)");
    else toast("Ошибка сервера (" + code + ")");
  });

  // Двойное подтверждение для кнопок с data-confirm:
  // первый клик меняет подпись, второй отправляет форму.
  document.body.addEventListener("click", function (evt) {
    var btn = evt.target.closest("button[data-confirm]");
    if (!btn) return;
    var form = btn.closest("form");
    if (!form) return;
    if (!btn.dataset.armed) {
      evt.preventDefault();
      btn.dataset.armed = "1";
      btn.dataset.origText = btn.textContent;
      btn.textContent = btn.dataset.confirm;
      setTimeout(function () {
        delete btn.dataset.armed;
        if (btn.dataset.origText) btn.textContent = btn.dataset.origText;
      }, 3000);
    }
  });
})();

// Переключатель светлой/тёмной темы (Bootstrap data-bs-theme).
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      localStorage.setItem("theme", next);
    });
  });
})();

// Пауза поллинга, пока пользователь печатает в форме добавления страницы.
(function () {
  document.body.addEventListener("htmx:beforeRequest", function (evt) {
    var el = evt.detail.elt;
    if (el.id !== "page-list") return;
    var details = document.querySelector("details.add-page");
    var typing = document.activeElement
      && document.activeElement.closest("details.add-page");
    if ((details && details.open) || typing) {
      evt.preventDefault();
    }
  });
})();

// Модальные окна: кнопки data-open-dialog / data-close-dialog,
// подстановка target_id для диалога добавления адреса.
(function () {
  document.addEventListener("click", function (evt) {
    var opener = evt.target.closest("[data-open-dialog]");
    if (opener) {
      var dialog = document.getElementById(opener.dataset.openDialog);
      if (!dialog) return;
      if (opener.dataset.targetId) {
        var tid = dialog.querySelector("#new-address-target-id");
        var rname = dialog.querySelector("#new-address-row-name");
        if (tid) tid.value = opener.dataset.targetId;
        if (rname) rname.textContent = opener.dataset.rowName || "";
      }
      dialog.showModal();
      return;
    }
    var closer = evt.target.closest("[data-close-dialog]");
    if (closer) {
      var d = closer.closest("dialog");
      if (d) d.close();
    }
  });

  // Фрагмент-ответ приходит без диалога: закрываем окна после подмены.
  // Если сервер вернул ошибку формы — диалог не закрываем, чтобы
  // сообщение было видно в контексте ввода.
  var lastDialog = null;
  document.addEventListener("submit", function (evt) {
    var d = evt.target.closest("dialog");
    if (d) lastDialog = d.id;
  }, true);

  document.body.addEventListener("htmx:afterSwap", function (evt) {
    var hasError = evt.detail.xhr.responseText.indexOf("alert-error") !== -1;
    document.querySelectorAll("dialog[open]").forEach(function (d) { d.close(); });
    if (hasError && lastDialog) {
      var d = document.getElementById(lastDialog);
      if (d) d.showModal();
    }
    lastDialog = null;
  });
})();
