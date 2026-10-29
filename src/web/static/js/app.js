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

  function scrollMessages() {
    const box = document.getElementById("messages");
    if (box) box.scrollTop = box.scrollHeight;
  }

  function autosize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
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
    if (action === "toggle-sidebar") {
      document.body.classList.toggle("sidebar-open");
    } else if (action === "dismiss") {
      target.closest(".flash")?.remove();
    }
  });

  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-theme-choice]")) storeTheme(e.target.value);
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
    }
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt;
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
