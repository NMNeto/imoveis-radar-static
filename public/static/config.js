/* Configuração pública do site estático.
 *
 * imageProxy:
 *   endpoint same-origin da Pages Function que faz proxy das imagens de
 *   Santander/Itaú/BB (os portais bloqueiam hotlink direto).  Deixe vazio para
 *   usar a URL original da imagem.
 */
window.IMOVEIS_CONFIG = {
  imageProxy: "/api/image",
};
