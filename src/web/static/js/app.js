/* Small progressive enhancements; everything works through HTMX + forms. */
(function () {
  "use strict";
  const root = document.documentElement;

  function storeTheme(theme) {
    root.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch (e) { /* private mode */ }
    document.querySelectorAll("[data-theme-choice]").forEach((r) => { r.checked = r.value === theme; });
    document.querySelectorAll("[data-theme-set]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.themeSet === theme));
    });
  }

  const FONTS = ["modern", "classic", "mono"];
  function storeFont(font) {
    if (!FONTS.includes(font)) font = "modern";
    root.dataset.font = font;
    try { localStorage.setItem("font", font); } catch (e) { /* private mode */ }
    document.querySelectorAll("[data-font-choice]").forEach((r) => { r.checked = r.value === font; });
  }

  const SIZES = ["small", "normal", "large"];
  function storeSize(size) {
    if (!SIZES.includes(size)) size = "normal";
    root.dataset.size = size;
    try { localStorage.setItem("size", size); } catch (e) { /* private mode */ }
    document.querySelectorAll("[data-size-choice]").forEach((r) => { r.checked = r.value === size; });
  }

  function scrollMessages() {
    const box = document.getElementById("messages");
    if (box) box.scrollTop = box.scrollHeight;
  }

  function autosize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
  }

  /* Elapsed-time counter and status phases while a question is being answered. */
  const asking = { timer: null, started: 0 };
  const PHASES = [
    [0, "Searching your documents…"],
    [8, "Reading the passages and planning the answer…"],
    [20, "Writing the answer…"],
    [45, "Still working — the AI service may be busy…"],
    [90, "Taking unusually long. You can stop and try again…"],
  ];

  function startAsking() {
    asking.started = Date.now();
    const elapsed = document.querySelector("[data-elapsed]");
    const status = document.querySelector("[data-status]");
    const tick = () => {
      const s = Math.round((Date.now() - asking.started) / 1000);
      if (elapsed) elapsed.textContent = s + " s";
      if (status) {
        let text = PHASES[0][1];
        for (const [from, label] of PHASES) if (s >= from) text = label;
        status.textContent = text;
      }
    };
    tick();
    clearInterval(asking.timer);
    asking.timer = setInterval(tick, 1000);
  }

  function stopAsking() {
    clearInterval(asking.timer);
    asking.timer = null;
  }

  function appendStoppedNote(question) {
    const box = document.getElementById("messages");
    if (!box) return;
    document.getElementById("welcome")?.remove();
    const user = document.createElement("article");
    user.className = "msg msg-user";
    user.innerHTML = '<div class="bubble"></div>';
    user.querySelector(".bubble").textContent = question;
    const note = document.createElement("article");
    note.className = "msg msg-assistant";
    note.innerHTML = '<div class="avatar" aria-hidden="true"></div><div class="msg-body"><p class="answered-by">Stopped</p>' +
      '<div class="prose"><p>Stopped before an answer was ready. Ask again or rephrase the question.</p></div></div>';
    box.append(user, note);
    box.scrollTop = box.scrollHeight;
  }

  function flash(message, hint) {
    const area = document.getElementById("flash");
    if (!area) return;
    area.innerHTML =
      '<div class="flash flash-error" role="alert"><span class="flash-icon">×</span><div class="flash-body">' +
      "<strong></strong><p></p></div>" +
      '<button class="icon-btn icon-btn-small" type="button" data-action="dismiss" aria-label="Dismiss">×</button></div>';
    area.querySelector("strong").textContent = message;
    area.querySelector("p").textContent = hint || "";
  }

  document.addEventListener("DOMContentLoaded", () => {
    storeTheme(root.dataset.theme || "system");
    storeFont(root.dataset.font || "modern");
    storeSize(root.dataset.size || "normal");
    scrollMessages();

    const question = document.getElementById("question");
    if (question) {
      question.addEventListener("input", () => autosize(question));
      question.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          if (question.value.trim()) question.form.requestSubmit();
        }
      });
      question.focus();
    }

    const input = document.getElementById("file-input");
    const zone = document.querySelector("[data-dropzone]");
    const names = document.querySelector("[data-file-names]");
    const showNames = () => {
      if (!names || !input) return;
      const files = Array.from(input.files).map((f) => f.name);
      names.textContent = files.length ? files.length + " selected: " + files.join(", ") : "";
      names.classList.remove("warn");
      zone?.classList.remove("needs-file");
    };
    if (input) input.addEventListener("change", showNames);
    if (zone && input) {
      ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("dragover"); }));
      ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("dragover"); }));
      zone.addEventListener("drop", (e) => { input.files = e.dataTransfer.files; showNames(); });
    }
  });

  document.addEventListener("click", (e) => {
    const themeButton = e.target.closest("[data-theme-set]");
    if (themeButton) { storeTheme(themeButton.dataset.themeSet); return; }
    const target = e.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    if (action === "stop-question") {
      const form = document.getElementById("composer");
      const question = form?.dataset.pendingQuestion || "";
      const token = document.getElementById("ask-token")?.value;
      if (token) {
        const body = new URLSearchParams({ ask_token: token });
        fetch("/ask/stop", { method: "POST", body, keepalive: true }).catch(() => {});
      }
      htmx.trigger(form, "htmx:abort");
      stopAsking();
      appendStoppedNote(question);
    } else if (action === "toggle-sidebar") {
      document.body.classList.toggle("sidebar-open");
    } else if (action === "dismiss") {
      target.closest(".flash")?.remove();
    }
  });

  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-theme-choice]")) storeTheme(e.target.value);
    if (e.target.matches("[data-font-choice]")) storeFont(e.target.value);
    if (e.target.matches("[data-size-choice]")) storeSize(e.target.value);
    if (e.target.matches("[data-model-select]")) {
      const custom = e.target.parentElement.querySelector("[data-model-custom]");
      if (custom) { custom.hidden = e.target.value !== "__custom__"; if (!custom.hidden) custom.focus(); }
    }
    if (e.target.matches(".scope-list input")) {
      const checked = document.querySelectorAll(".scope-list input:checked").length;
      const label = document.querySelector("[data-scope-label]");
      if (label) label.textContent = checked ? checked + " selected document" + (checked > 1 ? "s" : "") : "all documents";
    }
  });

  /* HTMX lifecycle */
  document.addEventListener("htmx:beforeRequest", (e) => {
    // "Add documents" with nothing chosen: explain inline and open the file picker instead of sending.
    const form = e.detail.elt;
    if (form.id === "upload-form") {
      const input = document.getElementById("file-input");
      if (input && input.files.length === 0) {
        e.preventDefault();
        const names = document.querySelector("[data-file-names]");
        if (names) { names.textContent = "Choose at least one file first."; names.classList.add("warn"); }
        document.querySelector("[data-dropzone]")?.classList.add("needs-file");
        input.click();
        return;
      }
    }
    if (e.detail.elt.closest && e.detail.elt.closest("#messages, #composer")) {
      document.getElementById("flash")?.replaceChildren();
      const composer = document.getElementById("composer");
      const params = e.detail.requestConfig && e.detail.requestConfig.parameters;
      if (composer) composer.dataset.pendingQuestion = (params && params.question) || document.getElementById("question")?.value || "";
      // A fresh token identifies this question so Stop can cancel it on the server.
      const tokenField = document.getElementById("ask-token");
      const token = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)).replace(/[^A-Za-z0-9-]/g, "");
      if (tokenField) tokenField.value = token;
      if (params) params.ask_token = token;
      startAsking();
    }
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt;
    if (form.closest && form.closest("#messages, #composer")) stopAsking();
    if (form.id === "composer" && e.detail.successful) {
      const q = document.getElementById("question");
      if (q) { q.value = ""; autosize(q); q.focus(); }
    }
    if (form.id === "upload-form" && e.detail.successful) {
      form.reset();
      const names = document.querySelector("[data-file-names]");
      if (names) names.textContent = "";
    }
  });
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "messages") scrollMessages();
    document.body.classList.remove("sidebar-open");
  });
  document.addEventListener("htmx:responseError", (e) => {
    flash("Something went wrong on the server.", "Status " + e.detail.xhr.status + ". Please try again.");
  });
  document.addEventListener("htmx:sendError", () => {
    flash("Couldn't reach the app.", "Check that it is still running, then try again.");
  });
})();
