/* Configuração pública do site estático.
 *
 * imageProxy:
 *   endpoint same-origin da Pages Function que faz proxy das imagens de
 *   Santander/Itaú/BB (os portais bloqueiam hotlink direto).  Deixe vazio para
 *   usar a URL original da imagem.
 *
 * actionsUrl:
 *   página do workflow "Atualizar imóveis" no GitHub Actions.  O botão
 *   "Atualizar agora" abre essa página; a atualização em si roda no GitHub.
 */
window.IMOVEIS_CONFIG = {
  imageProxy: "/api/image",
  actionsUrl:
    "https://github.com/NMNeto/imoveis-radar-static/actions/workflows/atualizar-imoveis.yml",
  repositoryUrl: "https://github.com/NMNeto/imoveis-radar-static",
};
