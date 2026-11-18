/* static/js/app.js
 * Comportamiento común del panel, del portal, del sitio público y del ingreso
 * (JS vanilla, sin dependencias salvo Bootstrap):
 * - menú lateral (abrir/cerrar, Esc, foco accesible)
 * - tema claro/oscuro guardado en el navegador
 * - link activo del menú según la URL
 * - cerrar mensajes (flash)
 */
(function () {
  "use strict";

  /* ---------- Tema ---------- */
  const CLAVE_TEMA = "taller-tema";
  /* Botones con [data-cc-tema] (partials/_tema_boton.html); el ícono muestra el modo al que se pasa. */
  const aplicarTema = (tema, guardar) => {
    document.documentElement.setAttribute("data-bs-theme", tema);
    if (guardar) {
      try { localStorage.setItem(CLAVE_TEMA, tema); } catch (e) { /* modo privado */ }
    }
    const texto = tema === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
    document.querySelectorAll("[data-cc-tema]").forEach((b) => {
      b.setAttribute("aria-label", texto);
      b.setAttribute("title", texto);
    });
    document.querySelectorAll("[data-cc-tema-icono]").forEach((i) => {
      i.className = tema === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    aplicarTema(document.documentElement.getAttribute("data-bs-theme") || "dark", false);
    document.querySelectorAll("[data-cc-tema]").forEach((b) => {
      b.addEventListener("click", () => {
        const actual = document.documentElement.getAttribute("data-bs-theme") || "dark";
        aplicarTema(actual === "dark" ? "light" : "dark", true);
      });
    });

    /* ---------- Menú lateral ---------- */
    const layout = document.getElementById("layout");
    const flyout = document.getElementById("ccFlyout");
    const toggles = document.querySelectorAll("[data-cc-flyout-toggle]");
    let ultimoFoco = null;

    const marcar = (abierto) => {
      toggles.forEach((b) => b.setAttribute("aria-expanded", abierto ? "true" : "false"));
      if (flyout) flyout.setAttribute("aria-hidden", abierto ? "false" : "true");
    };
    const abrir = () => {
      if (!layout) return;
      ultimoFoco = document.activeElement;
      layout.classList.add("cc-flyout-open");
      document.body.classList.add("cc-scroll-lock");
      marcar(true);
      const primero = flyout && flyout.querySelector('a, button, [tabindex]:not([tabindex="-1"])');
      if (primero) primero.focus({ preventScroll: true });
    };
    const cerrar = () => {
      if (!layout) return;
      layout.classList.remove("cc-flyout-open");
      document.body.classList.remove("cc-scroll-lock");
      marcar(false);
      if (ultimoFoco && ultimoFoco.focus) ultimoFoco.focus({ preventScroll: true });
    };

    toggles.forEach((b) => b.addEventListener("click", () => {
      layout && layout.classList.contains("cc-flyout-open") ? cerrar() : abrir();
    }));
    document.querySelectorAll("[data-cc-flyout-close]").forEach((b) => b.addEventListener("click", cerrar));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrar(); });
    document.querySelectorAll(".cc-flyout a").forEach((a) => a.addEventListener("click", cerrar));
    marcar(false);

    /* ---------- Link activo ---------- */
    const normalizar = (p) => (p || "/").split("?")[0].replace(/\/+$/, "") || "/";
    const actual = normalizar(window.location.pathname);
    const coincide = (href) => {
      const h = normalizar(href);
      return h === actual || (h !== "/" && actual.startsWith(h + "/"));
    };
    const marcarActivo = (raiz) => {
      if (!raiz) return;
      const links = Array.from(raiz.querySelectorAll('a[href^="/"]'));
      let mejor = -1;
      links.forEach((a) => {
        if (coincide(a.getAttribute("href"))) mejor = Math.max(mejor, normalizar(a.getAttribute("href")).length);
      });
      links.forEach((a) => {
        const activo = mejor >= 0 && coincide(a.getAttribute("href")) &&
          normalizar(a.getAttribute("href")).length === mejor;
        a.classList.toggle("is-active", activo);
        if (activo) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      });
    };
    marcarActivo(document.querySelector(".cc-flyout"));
    marcarActivo(document.querySelector(".cc-bottomnav"));
    marcarActivo(document.getElementById("ccMore"));

    /* Abrir la sección del menú que contiene el link activo */
    if (window.bootstrap) {
      document.querySelectorAll(".cc-acc").forEach((acc) => {
        const activo = acc.querySelector("a.cc-link.is-active");
        const seccion = activo && activo.closest(".accordion-item");
        const panel = seccion && seccion.querySelector(".accordion-collapse");
        if (panel) bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false }).show();
      });
    }

    /* ---------- Mensajes ---------- */
    document.querySelectorAll("[data-cc-flash-close]").forEach((b) => {
      b.addEventListener("click", () => {
        const item = b.closest(".cc-flash-item");
        if (item) item.remove();
      });
    });
  });
})();
