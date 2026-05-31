#!/usr/bin/env python3
"""
Relatório Diário Afetivamente — Envia resumo do dia anterior via WhatsApp (Z-API)
Roda todo dia às 08:00 via cron ou launchd (macOS)
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────
# CONFIGURAÇÃO — preencha após criar conta Z-API
# ─────────────────────────────────────────────
ZAPI_INSTANCE     = os.getenv("ZAPI_INSTANCE", "")
ZAPI_TOKEN        = os.getenv("ZAPI_TOKEN",    "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")  # opcional — deixe vazio se não usar

# Números que vão receber o relatório (só dígitos, com DDI, sem + ou espaço)
DESTINATARIOS = [
    os.getenv("WHATS_NASSER", ""),  # Nasser
    "55991555342",
]

# URL da API do dashboard local (deve estar rodando)
DASHBOARD_API = "http://localhost:8765/api/dashboard"

# ─────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ─────────────────────────────────────────────

def buscar_dados_ontem():
    """Busca direto da API Umbler os dados de ontem, sem cache"""
    from urllib.parse import urlencode

    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    token  = os.getenv("UMBLER_TOKEN", "")
    org_id = os.getenv("UMBLER_ORG_ID", "")

    # Busca as 250 conversas mais recentes direto da Umbler
    params = urlencode({"organizationId": org_id, "take": 250})
    url = f"https://app-utalk.umbler.com/api/v1/chats?{params}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERRO] Falha ao buscar da Umbler: {e}")
        return None

    # Filtra só as conversas com atividade ontem
    itens_ontem = [
        c for c in raw.get("items", [])
        if ((c.get("contact") or {}).get("lastActiveUTC") or
            c.get("eventAtUTC") or c.get("createdAtUTC") or "")[:10] == ontem
    ]

    print(f"[INFO] Conversas com atividade em {ontem}: {len(itens_ontem)}")

    # Passa pelo dashboard local só para processar (sem cache)
    url2 = f"{DASHBOARD_API}?data_inicio={ontem}&data_fim={ontem}&forcar=1"
    try:
        req2 = urllib.request.Request(url2, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req2, timeout=90) as resp2:
            return json.loads(resp2.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERRO] Falha ao processar dashboard: {e}")
        return None


def montar_mensagem(dados: dict) -> str:
    """Formata resumo diário compacto para WhatsApp"""
    ontem    = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
    resumo   = dados.get("resumo", {})

    total_novos = resumo.get("total_novos", 0)
    conversas   = dados.get("conversas", [])

    # Somente leads novos
    novos = [c for c in conversas if c.get("eh_novo")]
    agendados  = sum(1 for c in novos if c.get("agendamento") == "agendou")
    cancelados = sum(1 for c in novos if c.get("agendamento") == "cancelamento")

    # ── Especialidades — contagem só dos leads novos ──
    funil = {}
    for c in novos:
        for serv in (c.get("servicos") or []):
            if serv == "Não identificado":
                continue
            if serv not in funil:
                funil[serv] = {"total": 0, "agendou": 0}
            funil[serv]["total"] += 1
            if c.get("agendamento") == "agendou":
                funil[serv]["agendou"] += 1
    _ = resumo.get("funil_servico", {})  # não usado mais
    ESPECIALIDADES = [
        ("Avaliação Neuropsicológica", "🧠", "Avaliação"),
        ("Psiquiatria",                "💊", "Psiquiatria"),
        ("Psicoterapia",               "🛋️", "Psicologia"),
    ]
    linhas = ""
    maior = max((len(label) for _, _, label in ESPECIALIDADES), default=10)
    for chave, emoji, label in ESPECIALIDADES:
        info  = funil.get(chave, {})
        if not isinstance(info, dict):
            continue
        total = info.get("total", 0)
        agd   = info.get("agendou", 0)
        pontos = "." * (maior - len(label) + 4)
        agd_txt = f" ({agd}✅)" if agd > 0 else ""
        linhas += f"{emoji} {label} {pontos} *{total}* leads{agd_txt}\n"

    if not linhas:
        linhas = "  Sem dados\n"

    # ── Atendentes ──
    por_atend  = resumo.get("por_atendente", {})
    ATENDENTES = ["Amanda", "Ana", "Francine", "Lara"]
    atend_partes = []
    for nome in ATENDENTES:
        t = por_atend.get(nome, {}).get("total", 0)
        atend_partes.append(f"{nome} *{t}*")
    linha_atend = " · ".join(atend_partes)

    # ── Taxa de conversão ──
    total_geral = resumo.get("total", 0)
    taxa = round(agendados / total_geral * 100) if total_geral > 0 else 0

    msg = (
        f"🏥 *Afetivamente — {ontem}*\n\n"
        f"┌ 📥 *{total_novos}* novos  📅 *{agendados}* agend.  ❌ *{cancelados}* cancel.\n"
        f"└ 📈 Taxa de conversão: *{taxa}%*\n\n"
        f"{linhas}\n"
        f"👥 {linha_atend}\n"
        f"\n_Dashboard: http://localhost:8765_"
    )

    return msg


def enviar_whatsapp(numero: str, mensagem: str) -> bool:
    """Envia mensagem via Z-API"""
    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}/send-text"
    payload = json.dumps({"phone": numero, "message": mensagem}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if ZAPI_CLIENT_TOKEN:
        headers["Client-Token"] = ZAPI_CLIENT_TOKEN
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"[OK] Enviado para {numero}: {result}")
            return True
    except Exception as e:
        print(f"[ERRO] Falha ao enviar para {numero}: {e}")
        return False


# ─────────────────────────────────────────────
# EXECUÇÃO PRINCIPAL
# ─────────────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Iniciando relatório diário...")

    dados = buscar_dados_ontem()
    if not dados:
        print("[ERRO] Sem dados. Abortando envio.")
        return

    mensagem = montar_mensagem(dados)
    print("\n─── Preview da mensagem ───")
    print(mensagem)
    print("──────────────────────────\n")

    ok = 0
    for numero in DESTINATARIOS:
        if not numero or len(numero) < 10:
            print(f"[AVISO] Número inválido ou não configurado: '{numero}'")
            continue
        if enviar_whatsapp(numero, mensagem):
            ok += 1

    print(f"[FIM] {ok}/{len(DESTINATARIOS)} mensagem(ns) enviada(s).")


if __name__ == "__main__":
    main()
