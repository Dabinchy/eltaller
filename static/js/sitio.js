/* static/js/sitio.js
 * Sitio público (JS vanilla, sin librerías):
 * - Galería: [data-galeria] con enlaces a[data-foto] (href = foto grande, data-epigrafe = texto).
 *   Abre la foto en grande; flechas, Esc y deslizar con el dedo para pasar. Si varias galerías
 *   están dentro de un [data-galeria-grupo], el visor recorre todas sus fotos.
 * - Video liviano: button[data-video] (URL para incrustar). No carga nada de YouTube/Vimeo hasta
 *   que se toca; recién ahí se reemplaza por el reproductor.
 */
(function () {
  "use strict";

  /* ---------- Video liviano ---------- */
  const reproducir = (boton) => {
    const url = boton.getAttribute("data-video");
    if (!url) return;
    const iframe = document.createElement("iframe");
    iframe.src = url + (url.indexOf("?") === -1 ? "?" : "&") + "autoplay=1";
    iframe.title = boton.getAttribute("aria-label") || "Video";
    iframe.allow = "accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; fullscreen";
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.allowFullscreen = true;
    boton.replaceWith(iframe);
  };
  document.addEventListener("click", (e) => {
    const boton = e.target.closest("[data-video]");
    if (boton) reproducir(boton);
  });
  // Al cerrar un modal con video, se lo frena (se vuelve a poner el botón).
  document.addEventListener("hidden.bs.modal", (e) => {
    const iframe = e.target.querySelector(".sitio-video iframe");
    if (!iframe || !iframe.dataset) return;
    const contenedor = iframe.parentElement;
    if (contenedor && contenedor.dataset.original) contenedor.innerHTML = contenedor.dataset.original;
  });
  document.querySelectorAll(".modal .sitio-video").forEach((c) => { c.dataset.original = c.innerHTML; });

  /* ---------- Galería ---------- */
  let visor = null;
  let fotos = [];
  let actual = 0;
  let ultimoFoco = null;

  const crearVisor = () => {
    visor = document.createElement("div");
    visor.className = "sitio-visor";
    visor.setAttribute("role", "dialog");
    visor.setAttribute("aria-modal", "true");
    visor.setAttribute("aria-label", "Foto ampliada");
    visor.hidden = true;
    visor.innerHTML =
      '<button type="button" class="sitio-visor-btn sitio-visor-cerrar" aria-label="Cerrar"><i class="bi bi-x-lg" aria-hidden="true"></i></button>' +
      '<button type="button" class="sitio-visor-btn sitio-visor-ant" aria-label="Foto anterior"><i class="bi bi-chevron-left" aria-hidden="true"></i></button>' +
      '<figure class="sitio-visor-figura"><img alt=""><figcaption></figcaption></figure>' +
      '<button type="button" class="sitio-visor-btn sitio-visor-sig" aria-label="Foto siguiente"><i class="bi bi-chevron-right" aria-hidden="true"></i></button>' +
      '<span class="sitio-visor-cuenta" aria-live="polite"></span>';
    document.body.appendChild(visor);
    visor.querySelector(".sitio-visor-cerrar").addEventListener("click", cerrar);
    visor.querySelector(".sitio-visor-ant").addEventListener("click", () => mostrar(actual - 1));
    visor.querySelector(".sitio-visor-sig").addEventListener("click", () => mostrar(actual + 1));
    visor.addEventListener("click", (e) => { if (e.target === visor) cerrar(); });

    let x0 = null;
    visor.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    visor.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 50) mostrar(actual + (dx < 0 ? 1 : -1));
      x0 = null;
    });
  };

  const mostrar = (i) => {
    if (!fotos.length) return;
    actual = (i + fotos.length) % fotos.length;
    const a = fotos[actual];
    const img = visor.querySelector("img");
    img.src = a.getAttribute("href");
    img.alt = a.querySelector("img") ? a.querySelector("img").alt : "";
    visor.querySelector("figcaption").textContent = a.getAttribute("data-epigrafe") || "";
    visor.querySelector(".sitio-visor-cuenta").textContent = fotos.length > 1 ? (actual + 1) + " / " + fotos.length : "";
    visor.classList.toggle("sitio-visor-una", fotos.length < 2);
  };

  const abrir = (lista, i) => {
    if (!visor) crearVisor();
    fotos = lista;
    ultimoFoco = document.activeElement;
    visor.hidden = false;
    document.body.classList.add("cc-scroll-lock");
    mostrar(i);
    visor.querySelector(".sitio-visor-cerrar").focus();
  };

  function cerrar() {
    if (!visor || visor.hidden) return;
    visor.hidden = true;
    visor.querySelector("img").removeAttribute("src");
    document.body.classList.remove("cc-scroll-lock");
    if (ultimoFoco && ultimoFoco.focus) ultimoFoco.focus();
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-galeria] a[data-foto]");
    if (!a) return;
    e.preventDefault();
    const grupo = a.closest("[data-galeria-grupo]") || a.closest("[data-galeria]");
    const lista = Array.from(grupo.querySelectorAll("a[data-foto]"));
    abrir(lista, lista.indexOf(a));
  });

  document.addEventListener("keydown", (e) => {
    if (!visor || visor.hidden) return;
    if (e.key === "Escape") cerrar();
    else if (e.key === "ArrowLeft") mostrar(actual - 1);
    else if (e.key === "ArrowRight") mostrar(actual + 1);
  });
})();
