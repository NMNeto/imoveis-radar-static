/* Configuração pública do site estático.
 *
 * imageProxy:
 *   endpoint same-origin da Pages Function que faz proxy das imagens de
 *   Santander/Itaú/BB (os portais bloqueiam hotlink direto).  Deixe vazio para
 *   usar a URL original da imagem.
 *
 * feedbackUrl / feedbackEmbedUrl:
 *   Google Form de sugestões.  O site abre o formulário em um modal; o link
 *   externo é o fallback caso o iframe não carregue.
 */
window.IMOVEIS_CONFIG = {
  imageProxy: "/api/image",
  feedbackUrl: "https://forms.gle/HnciJsM5Xzto8ATd6",
  feedbackEmbedUrl:
    "https://docs.google.com/forms/d/e/1FAIpQLSfoOU2TuvHjSBbWg9AARIBO0iuDBoYgObQtlfyMVlOzroqtGw/viewform?embedded=true",
};
