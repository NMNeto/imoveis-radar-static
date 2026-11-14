/*
 * Google Tag Manager — GTM-PQ5NNHX6.
 *
 * O container só é carregado depois do consentimento explícito do visitante
 * (chave `imoveis-radar-static:analytics-consent:v1` = "granted").  Sem
 * consentimento, nenhuma requisição é feita ao Google.
 *
 * A inicialização equivale ao snippet fornecido:
 *   window.dataLayer = window.dataLayer || [];
 *   function gtag(){ dataLayer.push(arguments); }
 *   gtag('js', new Date());
 * O arquivo é local para não exigir 'unsafe-inline' na CSP.
 */
(function () {
  "use strict";

  var GTM_ID = "GTM-PQ5NNHX6";
  var CONSENT_KEY = "imoveis-radar-static:analytics-consent:v1";

  window.dataLayer = window.dataLayer || [];
  window.gtag = function () {
    window.dataLayer.push(arguments);
  };
  window.gtag("js", new Date());

  window.__gtmConsentGranted = function () {
    try {
      return window.localStorage.getItem(CONSENT_KEY) === "granted";
    } catch (error) {
      return false;
    }
  };

  window.__loadGTM = function () {
    if (window.__gtmLoaded || !window.__gtmConsentGranted()) {
      return false;
    }
    window.dataLayer.push({
      "gtm.start": new Date().getTime(),
      event: "gtm.js",
    });
    var script = document.createElement("script");
    script.async = true;
    script.src =
      "https://www.googletagmanager.com/gtm.js?id=" +
      encodeURIComponent(GTM_ID);
    document.head.appendChild(script);
    window.__gtmLoaded = true;
    return true;
  };

  window.__loadGTM();
})();
