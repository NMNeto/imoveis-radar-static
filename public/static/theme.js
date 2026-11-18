/*
 * Tema claro/escuro.
 *
 * Carregado no <head> (sem defer) para evitar "flash" de tema errado: o
 * atributo data-theme é aplicado antes da primeira pintura. A escolha fica
 * salva em localStorage; sem escolha, segue a preferência do sistema.
 *
 * Qualquer elemento com [data-theme-toggle] vira um botão de alternância.
 */
(function () {
  "use strict";

  var KEY = "imoveis-radar-static:theme:v1";
  var root = document.documentElement;
  var DARK_COLOR = "#0e1319";
  var LIGHT_COLOR = "#0b2f6f";

  function stored() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (error) {
      return null;
    }
  }

  function systemTheme() {
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    } catch (error) {
      return "light";
    }
  }

  function current() {
    return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function syncButton(button) {
    var dark = current() === "dark";
    var label = dark ? "Desativar tema escuro" : "Ativar tema escuro";
    button.setAttribute("aria-pressed", dark ? "true" : "false");
    button.setAttribute("title", label);
    button.setAttribute("aria-label", label);
  }

  function apply(theme, persist) {
    var next = theme === "dark" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    if (persist) {
      try {
        window.localStorage.setItem(KEY, next);
      } catch (error) {
        /* armazenamento indisponível: mantém só nesta página */
      }
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", next === "dark" ? DARK_COLOR : LIGHT_COLOR);
    }
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var index = 0; index < buttons.length; index += 1) {
      syncButton(buttons[index]);
    }
  }

  apply(stored() || systemTheme(), false);

  window.__theme = {
    get: current,
    set: function (theme) {
      apply(theme, true);
    },
    toggle: function () {
      apply(current() === "dark" ? "light" : "dark", true);
    },
  };

  function bind() {
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var index = 0; index < buttons.length; index += 1) {
      (function (button) {
        syncButton(button);
        button.addEventListener("click", function () {
          window.__theme.toggle();
        });
      })(buttons[index]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  try {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function (event) {
        if (!stored()) apply(event.matches ? "dark" : "light", false);
      });
  } catch (error) {
    /* navegador sem addEventListener em MediaQueryList */
  }
})();
