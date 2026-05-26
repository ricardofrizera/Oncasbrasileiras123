// Supabase Edge Function — Open Graph preview para WhatsApp/redes sociais
// Deploy: supabase functions deploy og
//
// URL de compartilhamento: https://<PROJECT>.supabase.co/functions/v1/og?slug=<slug-da-materia>
//   ou, com domínio customizado: https://preview.seusite.com.br/<slug>

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// URL base do seu site no Lovable (troque pelo domínio real)
const SITE_BASE_URL = Deno.env.get("SITE_BASE_URL") ?? "https://seusite.com.br";

// Imagem padrão caso o artigo não tenha imagem própria (1200x630px recomendado)
const DEFAULT_IMAGE = Deno.env.get("DEFAULT_OG_IMAGE") ?? `${SITE_BASE_URL}/og-default.jpg`;

// User-agents de bots de redes sociais
const BOT_AGENTS = [
  "whatsapp",
  "facebookexternalhit",
  "twitterbot",
  "linkedinbot",
  "slackbot",
  "telegrambot",
  "googlebot",
  "bingbot",
  "embedly",
  "outbrain",
  "pinterest",
];

function isBot(userAgent: string): boolean {
  const ua = userAgent.toLowerCase();
  return BOT_AGENTS.some((bot) => ua.includes(bot));
}

function buildOgHtml(artigo: {
  titulo: string;
  resumo: string;
  slug: string;
  imagem_url?: string | null;
}): string {
  const url = `${SITE_BASE_URL}/noticias/${artigo.slug}`;
  const image = artigo.imagem_url || DEFAULT_IMAGE;
  const title = artigo.titulo.replace(/"/g, "&quot;");
  const description = artigo.resumo.replace(/"/g, "&quot;");

  return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>${title}</title>

  <!-- Open Graph (WhatsApp, Facebook, LinkedIn) -->
  <meta property="og:type"        content="article" />
  <meta property="og:site_name"   content="Onças Brasileiras" />
  <meta property="og:url"         content="${url}" />
  <meta property="og:title"       content="${title}" />
  <meta property="og:description" content="${description}" />
  <meta property="og:image"       content="${image}" />
  <meta property="og:image:width"  content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt"   content="${title}" />

  <!-- Twitter Card -->
  <meta name="twitter:card"        content="summary_large_image" />
  <meta name="twitter:title"       content="${title}" />
  <meta name="twitter:description" content="${description}" />
  <meta name="twitter:image"       content="${image}" />

  <!-- Meta description padrão -->
  <meta name="description" content="${description}" />

  <!-- Redireciona o navegador humano para o site real imediatamente -->
  <meta http-equiv="refresh" content="0; url=${url}" />
  <link rel="canonical" href="${url}" />
</head>
<body>
  <p>Redirecionando… <a href="${url}">Clique aqui se não for redirecionado.</a></p>
</body>
</html>`;
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);

  // Aceita /og?slug=xxx  OU  /og/xxx
  let slug = url.searchParams.get("slug") ?? url.pathname.replace(/^\/og\/?/, "");

  if (!slug) {
    return new Response("Parâmetro 'slug' obrigatório.", { status: 400 });
  }

  // Remove barras extras
  slug = slug.replace(/^\/+|\/+$/g, "");

  const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  const { data, error } = await sb
    .from("artigos")
    .select("titulo, resumo, slug, imagem_url")
    .eq("slug", slug)
    .eq("status", "publicado")   // só artigos publicados
    .maybeSingle();

  if (error || !data) {
    // Artigo não encontrado → redireciona para home
    return Response.redirect(`${SITE_BASE_URL}/`, 302);
  }

  const userAgent = req.headers.get("user-agent") ?? "";

  // Bot de rede social → serve HTML com OG tags
  if (isBot(userAgent)) {
    return new Response(buildOgHtml(data), {
      status: 200,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
      },
    });
  }

  // Navegador real → redireciona diretamente para o site
  return Response.redirect(`${SITE_BASE_URL}/noticias/${slug}`, 302);
});
