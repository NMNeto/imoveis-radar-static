/**
 * Pages Function: proxy de imagens de BB, Santander e Itaú.
 *
 * Os portais bloqueiam hotlink direto (403) para alguns provedores.  Esta
 * função reproduz o comportamento do `/api/image` do projeto original:
 * valida uma allowlist de hosts, baixa a imagem e a mantém no cache de borda
 * da Cloudflare por 7 dias.  Não armazena nada em disco/repositório.
 *
 * Limite de segurança: 20 MB por imagem.
 */

const ALLOWED_HOSTS = new Set([
  "shi.santander.com.br",
  "www.seuimovelbb.com.br",
  "cdn.frazaoleiloes.com.br",
  "imagens.portalzuk.com.br",
  "cdn1.megaleiloes.com.br",
  "cdn-biasi.blueintra.com",
  "armazupleilaovipprd.blob.core.windows.net",
  "www.itau.com.br",
]);

const MAX_BYTES = 20 * 1024 * 1024;
const CACHE_SECONDS = 604800;

const REFERERS = {
  "shi.santander.com.br": "https://www.santanderimoveis.com.br/",
  "www.seuimovelbb.com.br": "https://www.seuimovelbb.com.br/",
  "www.itau.com.br": "https://www.itau.com.br/imoveis-itau/",
  "cdn.frazaoleiloes.com.br": "https://www.itau.com.br/",
  "imagens.portalzuk.com.br": "https://www.itau.com.br/",
  "cdn1.megaleiloes.com.br": "https://www.itau.com.br/",
  "cdn-biasi.blueintra.com": "https://www.itau.com.br/",
  "armazupleilaovipprd.blob.core.windows.net": "https://www.itau.com.br/",
};

function errorResponse(status, message) {
  return new Response(JSON.stringify({ ok: false, error: message }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

export async function onRequestGet(context) {
  const requestUrl = new URL(context.request.url);
  const rawUrl = requestUrl.searchParams.get("url");
  if (!rawUrl) return errorResponse(400, "Parâmetro url obrigatório");

  let target;
  try {
    target = new URL(rawUrl);
  } catch (error) {
    return errorResponse(400, "URL inválida");
  }
  if (target.protocol !== "https:") {
    return errorResponse(400, "Apenas HTTPS é permitido");
  }
  if (target.port && target.port !== "443") {
    return errorResponse(400, "Porta não permitida");
  }
  if (!ALLOWED_HOSTS.has(target.hostname)) {
    return errorResponse(400, "Host de imagem não permitido");
  }

  const cache = caches.default;
  const cacheKey = new Request(target.toString(), { method: "GET" });
  try {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
  } catch (error) {
    // Cache indisponível: segue para a origem.
  }

  let upstream;
  try {
    upstream = await fetch(target.toString(), {
      method: "GET",
      redirect: "follow",
      headers: {
        "User-Agent":
          "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36",
        Accept: "image/avif,image/webp,image/png,image/jpeg,image/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        Referer: REFERERS[target.hostname] || `${target.protocol}//${target.hostname}/`,
      },
      cf: { cacheEverything: true, cacheTtl: CACHE_SECONDS },
    });
  } catch (error) {
    return errorResponse(502, "Não foi possível baixar a imagem");
  }

  if (!upstream.ok) {
    return errorResponse(502, `Origem respondeu ${upstream.status}`);
  }

  const finalUrl = new URL(upstream.url);
  if (!ALLOWED_HOSTS.has(finalUrl.hostname)) {
    return errorResponse(502, "Redirecionamento não permitido");
  }

  const contentType = (upstream.headers.get("content-type") || "")
    .split(";")[0]
    .trim()
    .toLowerCase();
  if (!contentType.startsWith("image/")) {
    return errorResponse(502, "Conteúdo não é imagem");
  }

  const declared = Number(upstream.headers.get("content-length") || 0);
  if (declared > MAX_BYTES) {
    return errorResponse(413, "Imagem maior que 20 MB");
  }

  const buffer = await upstream.arrayBuffer();
  if (buffer.byteLength > MAX_BYTES) {
    return errorResponse(413, "Imagem maior que 20 MB");
  }

  const response = new Response(buffer, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(buffer.byteLength),
      "Cache-Control": `public, max-age=${CACHE_SECONDS}, immutable`,
      "X-Content-Type-Options": "nosniff",
      "Access-Control-Allow-Origin": "*",
    },
  });

  try {
    context.waitUntil(cache.put(cacheKey, response.clone()));
  } catch (error) {
    // Sem cache: a resposta ainda é válida.
  }
  return response;
}
