#!/usr/bin/env python3
"""MCP server — Economia Capixaba content generator."""

import os
import re
import json
import unicodedata
import anthropic
from mcp.server.fastmcp import FastMCP
from prompt_ec import SYSTEM_PROMPT, PORTAL_PROMPT

mcp = FastMCP("economia-capixaba")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY não configurada.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


@mcp.prompt()
def economia_capixaba_instagram() -> str:
    """Prompt EC 2.0 — gerador de conteúdo para Instagram."""
    return SYSTEM_PROMPT


@mcp.prompt()
def economia_capixaba_portal() -> str:
    """Prompt EC 2.0 — gerador de matéria completa para o portal."""
    return PORTAL_PROMPT


@mcp.tool()
def gerar_instagram(materia: str) -> str:
    """Gera título, legenda e versão narrada para Instagram a partir de uma matéria.

    Args:
        materia: Texto completo da matéria jornalística de origem.
    """
    client = _get_client()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Gere o conteúdo para Instagram baseado na matéria abaixo. "
                    "Siga rigorosamente a estrutura obrigatória: "
                    "1) TÍTULO PARA INSTAGRAM, 2) LEGENDA PARA INSTAGRAM, "
                    "3) VERSÃO NARRADA PARA INSTAGRAM.\n\n"
                    f"MATÉRIA:\n{materia}"
                ),
            }
        ],
    )
    return response.content[0].text


@mcp.tool()
def gerar_materia_portal(materia: str) -> str:
    """Gera matéria completa para o portal Economia Capixaba.

    Args:
        materia: Texto completo da matéria jornalística de origem.
    """
    client = _get_client()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=PORTAL_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Escreva a matéria completa para o portal Economia Capixaba "
                    "baseada no conteúdo abaixo. Identifique qual transformação "
                    "econômica está acontecendo no Espírito Santo e estruture o texto "
                    "com lead forte, dados relevantes e impacto econômico regional.\n\n"
                    f"MATÉRIA DE ORIGEM:\n{materia}"
                ),
            }
        ],
    )
    return response.content[0].text


@mcp.tool()
def gerar_tudo(materia: str) -> str:
    """Gera de uma vez: Instagram (título + legenda + narração) e matéria completa para o portal.

    Args:
        materia: Texto completo da matéria jornalística de origem.
    """
    client = _get_client()

    instagram = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Gere o conteúdo para Instagram baseado na matéria abaixo. "
                    "Siga rigorosamente a estrutura obrigatória: "
                    "1) TÍTULO PARA INSTAGRAM, 2) LEGENDA PARA INSTAGRAM, "
                    "3) VERSÃO NARRADA PARA INSTAGRAM.\n\n"
                    f"MATÉRIA:\n{materia}"
                ),
            }
        ],
    )

    portal = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=PORTAL_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Escreva a matéria completa para o portal Economia Capixaba "
                    "baseada no conteúdo abaixo. Identifique qual transformação "
                    "econômica está acontecendo no Espírito Santo e estruture o texto "
                    "com lead forte, dados relevantes e impacto econômico regional.\n\n"
                    f"MATÉRIA DE ORIGEM:\n{materia}"
                ),
            }
        ],
    )

    result = {
        "instagram": instagram.content[0].text,
        "portal": portal.content[0].text,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def publicar_supabase(
    titulo: str,
    conteudo: str,
    resumo: str,
    ig_titulo: str,
    ig_legenda: str,
    ig_narrado: str,
    transcricao: str = "",
    fonte_original: str = "",
    categoria: str = "",
) -> str:
    """Salva matéria no Supabase como rascunho. Retorna o ID do artigo criado.

    Args:
        titulo: Título da matéria para o portal.
        conteudo: Texto completo da matéria em HTML simples.
        resumo: Resumo em 2-3 frases para meta description.
        ig_titulo: Título gerado para o Instagram.
        ig_legenda: Legenda completa para o Instagram.
        ig_narrado: Versão narrada (máx 290 chars) para o Instagram.
        transcricao: Texto original transcrito do áudio (opcional).
        fonte_original: URL da matéria de origem (opcional).
        categoria: Categoria do artigo (opcional).
    """
    try:
        from supabase import create_client
    except ImportError:
        return "Erro: instale o pacote supabase (pip install supabase)"

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return "Erro: SUPABASE_URL e SUPABASE_SERVICE_KEY não configuradas."

    s = unicodedata.normalize("NFKD", titulo.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s)
    slug = re.sub(r"[\s_]+", "-", s).strip("-")[:80]

    sb = create_client(url, key)
    result = sb.table("artigos").insert({
        "titulo":          titulo,
        "slug":            slug,
        "conteudo":        conteudo,
        "resumo":          resumo,
        "ig_titulo":       ig_titulo,
        "ig_legenda":      ig_legenda,
        "ig_narrado":      ig_narrado,
        "status":          "rascunho",
        "autor":           "Economia Capixaba",
        "transcricao":     transcricao,
        "fonte_original":  fonte_original,
        "categoria":       categoria,
    }).execute()

    artigo_id = result.data[0]["id"]
    return f"Rascunho criado com sucesso. ID: {artigo_id} | Slug: {slug}"


if __name__ == "__main__":
    mcp.run()
