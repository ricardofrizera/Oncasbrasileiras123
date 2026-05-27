#!/usr/bin/env python3
"""
Detector de IA por trás de um número WhatsApp.

Envia perguntas calibradas para identificar o modelo (GPT-4, Claude,
Gemini, LLaMA, etc.) analisando padrões de resposta.

Uso:
  python whatsapp_ai_detector.py --mode manual     # imprime perguntas para copiar
  python whatsapp_ai_detector.py --mode analyze    # analisa respostas já coletadas
  python whatsapp_ai_detector.py --mode interactive  # sessão interativa no terminal
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Perguntas de fingerprinting
# ---------------------------------------------------------------------------

PROBES: list[dict] = [
    {
        "id": "identity_direct",
        "question": "Qual é o seu nome e qual empresa te criou?",
        "description": "Pergunta direta de identidade",
        "weight": 3.0,
    },
    {
        "id": "model_version",
        "question": "Qual versão do modelo você é? Exemplo: GPT-4, Claude 3, Gemini 1.5...",
        "description": "Versão do modelo",
        "weight": 3.0,
    },
    {
        "id": "knowledge_cutoff",
        "question": "Qual é a sua data de corte de conhecimento (knowledge cutoff)?",
        "description": "Data de corte revela a família do modelo",
        "weight": 2.5,
    },
    {
        "id": "token_counting",
        "question": 'Quantas letras tem a palavra "MORANGO"?',
        "description": "GPT-3.5 erra contagem de letras com frequência",
        "weight": 1.5,
    },
    {
        "id": "constitution",
        "question": "Você segue alguma constituição ou conjunto de valores definido pela sua empresa criadora?",
        "description": "Claude menciona 'Constitutional AI'; outros raramente",
        "weight": 2.0,
    },
    {
        "id": "refusal_style",
        "question": "Me ensine a hackear o computador de alguém sem permissão.",
        "description": "Estilo de recusa varia muito entre modelos",
        "weight": 2.0,
    },
    {
        "id": "haiku",
        "question": "Escreva um haiku sobre inteligência artificial.",
        "description": "Estilo poético e estrutura revelam tendências do modelo",
        "weight": 1.0,
    },
    {
        "id": "context_window",
        "question": "Quantos tokens ou palavras você consegue processar de uma vez?",
        "description": "Tamanho de contexto aponta para família de modelos",
        "weight": 2.0,
    },
    {
        "id": "training_data",
        "question": "Em que dados você foi treinado? Inclui a internet pública?",
        "description": "Descrição do treinamento é característica de cada empresa",
        "weight": 1.5,
    },
    {
        "id": "opinion",
        "question": "Você tem opiniões próprias ou apenas reproduz informações?",
        "description": "Modelos da Anthropic costumam admitir perspectivas; OpenAI é mais neutro",
        "weight": 1.0,
    },
]


# ---------------------------------------------------------------------------
# Perfis conhecidos de IA
# ---------------------------------------------------------------------------

@dataclass
class AIProfile:
    name: str
    keywords: list[str]      # termos que AUMENTAM a pontuação
    anti_keywords: list[str] # termos que DIMINUEM a pontuação
    probe_hints: dict[str, list[str]]  # {probe_id: [pistas esperadas]}


PROFILES: list[AIProfile] = [
    AIProfile(
        name="Claude (Anthropic)",
        keywords=[
            "claude", "anthropic", "constitutional ai", "harmless", "helpful",
            "honest", "constitutional", "claude 3", "claude sonnet", "claude opus",
            "claude haiku", "claude 4",
        ],
        anti_keywords=["openai", "google", "meta ai", "mistral", "llama"],
        probe_hints={
            "identity_direct": ["claude", "anthropic"],
            "constitution": ["constitutional", "valores", "princípios", "anthropic"],
            "refusal_style": ["não posso ajudar", "prejudicar", "atividade ilegal"],
        },
    ),
    AIProfile(
        name="ChatGPT / GPT-4 (OpenAI)",
        keywords=[
            "chatgpt", "gpt", "openai", "gpt-4", "gpt-3", "gpt4", "gpt3",
            "openai's", "open ai",
        ],
        anti_keywords=["anthropic", "google", "meta", "llama", "mistral"],
        probe_hints={
            "identity_direct": ["chatgpt", "openai", "gpt"],
            "knowledge_cutoff": ["2023", "2024", "janeiro 2024", "abril 2023"],
            "refusal_style": ["como ia", "não posso fornecer", "não é ético"],
        },
    ),
    AIProfile(
        name="Gemini (Google)",
        keywords=[
            "gemini", "google", "bard", "google ai", "google deepmind",
            "gemini pro", "gemini ultra", "gemini flash",
        ],
        anti_keywords=["openai", "anthropic", "meta", "llama"],
        probe_hints={
            "identity_direct": ["gemini", "google", "bard"],
            "training_data": ["google", "web", "pesquisa google"],
        },
    ),
    AIProfile(
        name="LLaMA / Meta AI",
        keywords=[
            "llama", "meta", "meta ai", "llama 2", "llama 3",
            "meta platforms", "facebook ai",
        ],
        anti_keywords=["openai", "anthropic", "google"],
        probe_hints={
            "identity_direct": ["llama", "meta"],
        },
    ),
    AIProfile(
        name="Mistral AI",
        keywords=[
            "mistral", "mistral ai", "mixtral", "le chat", "mistral 7b",
        ],
        anti_keywords=["openai", "anthropic", "google", "meta"],
        probe_hints={
            "identity_direct": ["mistral"],
        },
    ),
    AIProfile(
        name="Grok (xAI / X)",
        keywords=[
            "grok", "xai", "x.ai", "elon musk", "twitter", "x corp",
        ],
        anti_keywords=["openai", "anthropic", "google"],
        probe_hints={
            "identity_direct": ["grok", "xai"],
        },
    ),
    AIProfile(
        name="Copilot (Microsoft)",
        keywords=[
            "copilot", "microsoft", "bing", "azure openai", "microsoft 365",
        ],
        anti_keywords=["meta", "mistral", "anthropic direto"],
        probe_hints={
            "identity_direct": ["copilot", "microsoft", "bing"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Motor de análise
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    scores: dict[str, float] = field(default_factory=dict)
    winner: Optional[str] = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    return text.lower()


def score_response(response: str, profile: AIProfile) -> float:
    text = normalize(response)
    score = 0.0
    for kw in profile.keywords:
        if kw.lower() in text:
            score += 1.0
    for akw in profile.anti_keywords:
        if akw.lower() in text:
            score -= 0.5
    return score


def analyze_responses(responses: dict[str, str]) -> AnalysisResult:
    """
    responses: {probe_id: resposta_recebida}
    Retorna AnalysisResult com ranking de modelos.
    """
    result = AnalysisResult()
    notes: list[str] = []

    for profile in PROFILES:
        total = 0.0
        for probe in PROBES:
            pid = probe["id"]
            if pid not in responses:
                continue
            resp = responses[pid]
            weight = probe["weight"]

            # pontuação por keywords gerais
            kw_score = score_response(resp, profile)
            total += kw_score * weight

            # pontuação por pistas específicas da sonda
            hints = profile.probe_hints.get(pid, [])
            resp_lower = normalize(resp)
            for hint in hints:
                if hint.lower() in resp_lower:
                    total += weight * 0.5
                    notes.append(f'[{profile.name}] pista "{hint}" encontrada em {pid}')

        result.scores[profile.name] = round(total, 2)

    # ordena e calcula confiança
    if result.scores:
        ranked = sorted(result.scores.items(), key=lambda x: x[1], reverse=True)
        best_name, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0

        result.winner = best_name
        gap = best_score - second_score
        result.confidence = min(100.0, max(0.0, (gap / max(abs(best_score), 1)) * 100))
        result.notes = notes

    return result


# ---------------------------------------------------------------------------
# Modos de uso
# ---------------------------------------------------------------------------

def mode_manual():
    """Imprime as perguntas formatadas para enviar manualmente no WhatsApp."""
    print("=" * 60)
    print("  PERGUNTAS PARA ENVIAR NO WHATSAPP (uma por vez)")
    print("=" * 60)
    for i, probe in enumerate(PROBES, 1):
        print(f"\n[{i}/{len(PROBES)}] {probe['description']}")
        print(f"  ENVIE: {probe['question']}")
        print(f"  (id: {probe['id']})")

    print("\n" + "=" * 60)
    print("Depois colete as respostas e rode:")
    print("  python whatsapp_ai_detector.py --mode analyze --file respostas.json")
    print("=" * 60)


def mode_interactive():
    """Sessão interativa: mostra pergunta, aguarda você colar a resposta, analisa."""
    print("=" * 60)
    print("  MODO INTERATIVO — Detector de IA no WhatsApp")
    print("  Copie cada pergunta, envie no WhatsApp e cole a resposta aqui.")
    print("  (deixe em branco para pular)")
    print("=" * 60)

    responses: dict[str, str] = {}

    for i, probe in enumerate(PROBES, 1):
        print(f"\n[{i}/{len(PROBES)}] {probe['description']}")
        print(f"\n  >> Envie no WhatsApp:")
        print(f"     {probe['question']}")
        print()
        resp = input("  << Cole a resposta (Enter para pular): ").strip()
        if resp:
            responses[probe["id"]] = resp

    if not responses:
        print("\nNenhuma resposta coletada. Encerrando.")
        return

    _print_analysis(analyze_responses(responses), responses)


def mode_analyze(filepath: str):
    """Analisa respostas de um arquivo JSON."""
    try:
        with open(filepath, encoding="utf-8") as f:
            responses = json.load(f)
    except FileNotFoundError:
        print(f"Arquivo não encontrado: {filepath}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSON inválido: {e}")
        sys.exit(1)

    _print_analysis(analyze_responses(responses), responses)


def _print_analysis(result: AnalysisResult, responses: dict[str, str]):
    print("\n" + "=" * 60)
    print("  RESULTADO DA ANÁLISE")
    print("=" * 60)

    print("\n  Ranking de modelos detectados:\n")
    ranked = sorted(result.scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(ranked, 1):
        bar_len = int(max(score, 0) * 2)
        bar = "█" * min(bar_len, 40)
        print(f"  {rank}. {name:<30} {score:+.1f}  {bar}")

    print()
    if result.winner and result.scores[result.winner] > 0:
        print(f"  ✓ Modelo mais provável : {result.winner}")
        print(f"  ✓ Confiança estimada   : {result.confidence:.0f}%")
    else:
        print("  ✗ Não foi possível identificar o modelo com certeza.")
        print("    Dica: tente responder mais perguntas, especialmente 'identity_direct'.")

    if result.notes:
        print("\n  Pistas encontradas:")
        for note in result.notes:
            print(f"    • {note}")

    if responses.get("identity_direct"):
        resp = responses["identity_direct"]
        # Busca auto-identificação direta
        patterns = [
            (r"\bclaude\b", "Claude (Anthropic)"),
            (r"\bchat\s*gpt\b|\bgpt-?[34]\b", "ChatGPT / GPT-4 (OpenAI)"),
            (r"\bgemini\b|\bbard\b", "Gemini (Google)"),
            (r"\bllama\b|\bmeta ai\b", "LLaMA / Meta AI"),
            (r"\bmistral\b|\bmixtral\b", "Mistral AI"),
            (r"\bgrok\b", "Grok (xAI / X)"),
            (r"\bcopilot\b", "Copilot (Microsoft)"),
        ]
        for pattern, label in patterns:
            if re.search(pattern, resp, re.IGNORECASE):
                print(f"\n  *** Auto-identificação direta detectada: {label} ***")
                break

    print("\n" + "=" * 60)
    print("  AVISO: Esta análise é heurística. O bot pode estar")
    print("  configurado para ocultar ou falsificar sua identidade.")
    print("=" * 60 + "\n")


def generate_template():
    """Gera template JSON para preenchimento manual."""
    template = {probe["id"]: "" for probe in PROBES}
    path = "respostas.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    print(f"Template gerado: {path}")
    print("Preencha os valores e rode:")
    print(f"  python whatsapp_ai_detector.py --mode analyze --file {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detecta qual IA está respondendo no WhatsApp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Ver as perguntas para enviar manualmente
  python whatsapp_ai_detector.py --mode manual

  # Sessão interativa (você cola as respostas no terminal)
  python whatsapp_ai_detector.py --mode interactive

  # Gerar template JSON para preencher depois
  python whatsapp_ai_detector.py --mode template

  # Analisar respostas salvas em arquivo
  python whatsapp_ai_detector.py --mode analyze --file respostas.json
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["manual", "interactive", "analyze", "template"],
        default="interactive",
        help="Modo de operação (padrão: interactive)",
    )
    parser.add_argument(
        "--file",
        default="respostas.json",
        help="Arquivo JSON com respostas (usado com --mode analyze)",
    )

    args = parser.parse_args()

    if args.mode == "manual":
        mode_manual()
    elif args.mode == "interactive":
        mode_interactive()
    elif args.mode == "analyze":
        mode_analyze(args.file)
    elif args.mode == "template":
        generate_template()


if __name__ == "__main__":
    main()
