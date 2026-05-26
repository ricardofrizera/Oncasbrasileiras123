#!/usr/bin/env python3
"""Pipeline completo: áudio (ou texto) → matéria → Supabase rascunho.

Uso:
  python3 gerar_materia.py entrevista.mp3 [url_fonte]
  python3 gerar_materia.py materia.txt    [url_fonte]
"""

import sys
import os
import re
import json
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import anthropic
from supabase import create_client

from prompt_ec import SYSTEM_PROMPT, PORTAL_PROMPT

AUDIO_EXTENSOES = {".mp3", ".mp4", ".m4a", ".wav", ".webm", ".ogg", ".flac"}


# ── transcrição ──────────────────────────────────────────────────────────────

def transcrever(caminho: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    with open(caminho, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="pt",
        )
    return result.text


# ── geração de conteúdo ───────────────────────────────────────────────────────

def _extrair_json(texto: str) -> dict:
    """Extrai o primeiro bloco JSON válido de uma resposta do modelo."""
    match = re.search(r"```json\s*(.*?)\s*```", texto, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"JSON não encontrado:\n{texto[:400]}")


def gerar_instagram(materia: str, claude: anthropic.Anthropic) -> dict:
    resp = claude.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Gere o conteúdo para Instagram baseado na matéria abaixo.\n"
                "Retorne APENAS um JSON válido, sem nenhum texto fora dele, com as chaves:\n"
                '  "titulo"  : string\n'
                '  "legenda" : string\n'
                '  "narrado" : string (máximo 290 caracteres, sem link)\n\n'
                f"MATÉRIA:\n{materia}"
            ),
        }],
    )
    return _extrair_json(resp.content[0].text)


def gerar_portal(materia: str, claude: anthropic.Anthropic) -> dict:
    resp = claude.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=PORTAL_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Escreva a matéria completa para o portal Economia Capixaba.\n"
                "Retorne APENAS um JSON válido, sem nenhum texto fora dele, com as chaves:\n"
                '  "titulo"   : string\n'
                '  "resumo"   : string (2-3 frases para subtítulo/meta description)\n'
                '  "conteudo" : string (texto completo — use HTML simples: <p>, <h2>, <strong>)\n\n'
                f"MATÉRIA DE ORIGEM:\n{materia}"
            ),
        }],
    )
    return _extrair_json(resp.content[0].text)


# ── utilitários ───────────────────────────────────────────────────────────────

def gerar_slug(titulo: str) -> str:
    s = unicodedata.normalize("NFKD", titulo.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:80]


def publicar_supabase(dados: dict) -> str:
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )
    result = sb.table("artigos").insert(dados).execute()
    return result.data[0]["id"]


# ── pipeline principal ────────────────────────────────────────────────────────

def main(caminho: str, fonte: str = "", imagem_url: str = "") -> None:
    extensao = Path(caminho).suffix.lower()

    # 1. Obter texto base
    if extensao in AUDIO_EXTENSOES:
        print(f"[1/4] Transcrevendo áudio: {caminho}")
        texto_base = transcrever(caminho)
        print(f"      {len(texto_base)} caracteres transcritos.")
    else:
        print(f"[1/4] Lendo texto: {caminho}")
        texto_base = Path(caminho).read_text(encoding="utf-8")
        print(f"      {len(texto_base)} caracteres.")

    claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 2. Instagram
    print("[2/4] Gerando conteúdo para Instagram...")
    ig = gerar_instagram(texto_base, claude)

    # 3. Portal
    print("[3/4] Gerando matéria para o portal...")
    portal = gerar_portal(texto_base, claude)

    slug = gerar_slug(portal["titulo"])

    dados: dict = {
        "titulo":         portal["titulo"],
        "slug":           slug,
        "conteudo":       portal["conteudo"],
        "resumo":         portal.get("resumo", ""),
        "ig_titulo":      ig["titulo"],
        "ig_legenda":     ig["legenda"],
        "ig_narrado":     ig["narrado"],
        "status":         "rascunho",
        "autor":          "Economia Capixaba",
        "transcricao":    texto_base,
        "fonte_original": fonte,
    }
    if imagem_url:
        dados["imagem_url"] = imagem_url

    # 4. Supabase
    print("[4/4] Salvando rascunho no Supabase...")
    artigo_id = publicar_supabase(dados)

    # ── resultado ────────────────────────────────────────────────────────────
    separador = "─" * 60
    print(f"\n{separador}")
    print(f"  RASCUNHO CRIADO")
    print(f"  ID   : {artigo_id}")
    print(f"  Slug : {slug}")
    print(separador)

    print("\n── INSTAGRAM ───────────────────────────────────────────────")
    print(f"Título:\n{ig['titulo']}\n")
    print(f"Legenda:\n{ig['legenda']}\n")
    print(f"Narrado ({len(ig['narrado'])} chars):\n{ig['narrado']}")

    print("\n── PORTAL ──────────────────────────────────────────────────")
    print(f"Título:\n{portal['titulo']}\n")
    print(f"Resumo:\n{portal.get('resumo', '')}")
    print(separador)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 gerar_materia.py <arquivo.mp3|.txt> [url_fonte] [url_imagem]")
        sys.exit(1)
    fonte_url  = sys.argv[2] if len(sys.argv) > 2 else ""
    img_url    = sys.argv[3] if len(sys.argv) > 3 else ""
    main(sys.argv[1], fonte_url, img_url)
