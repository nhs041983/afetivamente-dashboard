#!/usr/bin/env python3
"""
Relatório Diário Afetivamente — Standalone
Roda direto no GitHub Actions, sem precisar do servidor local.
Busca dados da Umbler, processa e envia via Z-API.
"""

import os, json, urllib.request, urllib.parse
from datetime import datetime, timedelta

# ── Credenciais (vêm das variáveis de ambiente / GitHub Secrets) ──
UMBLER_TOKEN      = os.environ["UMBLER_TOKEN"].strip()
UMBLER_ORG_ID     = os.environ["UMBLER_ORG_ID"].strip()
ZAPI_INSTANCE     = os.environ["ZAPI_INSTANCE"].strip()
ZAPI_TOKEN        = os.environ["ZAPI_TOKEN"].strip()
ZAPI_CLIENT_TOKEN = os.environ.get("ZAPI_CLIENT_TOKEN", "").strip()

DESTINATARIOS = [
    n.strip() for n in os.environ.get("WHATS_DESTINATARIOS", "").split(",") if n.strip()
]

# ── Mapeamento de atendentes ──
MEMBROS = {
    "aGUzI5k5JQhSWCnq": "Nasser",
    "aKhv2bFJo5gKUvpe": "Francine",
    "aK81tFIEzPmA9Jfw":  "Ana",
    "aXOpvJ13uofmwuq9": "Lara",
    "__tag_amanda__":    "Amanda",
    "__tag_lara__":      "Lara",
}

TAG_SERVICO = {
    "AVALIAÇÃO NEUROPSICOLÓGICA": "Avaliação Neuropsicológica",
    "PSICOTERAPIA":               "Psicoterapia",
    "PSIQUIATRIA":                "Psiquiatria",
    "ACOLHIMENTO":                "Acolhimento",
    "FONOAUDIÓLOGA":              "Fonoaudiologia",
    "FONOAUDIOLOGIA":             "Fonoaudiologia",
    "NUTRICIONISTA":              "Nutrição",
    "MED FAMÍLIA":                "Medicina de Família",
}

KW_AGENDOU     = ["agendad", "consulta marcada", "confirmad", "horário marcado", "agendamos"]
KW_CANCELAMENTO = ["cancelou", "cancelar", "cancelamento", "desistiu", "não vai mais"]

# ─────────────────────────────────────────────
# BUSCA E PROCESSAMENTO
# ─────────────────────────────────────────────

def umbler_get(path, params=None):
    url = f"https://app-utalk.umbler.com/api/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    # Garante que o token só contém caracteres ASCII válidos para headers
    token_safe = UMBLER_TOKEN.encode("ascii", errors="ignore").decode("ascii").strip()
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token_safe}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def detectar_servico(tags):
    for t in tags:
        s = TAG_SERVICO.get(t.upper().strip())
        if s:
            return s
    return None


def detectar_agendamento(texto, tags):
    todas = " ".join(tags).upper()
    if "EM ATENDIMENTO" in todas:
        return "agendou"
    if any(k in texto for k in KW_AGENDOU):
        return "agendou"
    if any(k in texto for k in KW_CANCELAMENTO):
        return "cancelamento"
    return "nao_agendou"


def processar(chats, ontem):
    resultado = []
    for c in chats:
        contato    = c.get("contact") or {}
        membro     = c.get("organizationMember") or {}
        tags_c     = [t.get("name","") for t in (contato.get("tags") or [])]
        tags_ch    = [t.get("name","") for t in (c.get("tags") or [])]
        todas_tags = tags_c + tags_ch

        msg   = c.get("lastMessage") or {}
        texto = (msg.get("content") or msg.get("text") or "").lower()

        data_criacao = (c.get("createdAtUTC") or "")[:10]
        eh_novo      = data_criacao == ontem

        # Atendente
        atend_id = membro.get("id", "")
        nome_api = (membro.get("name") or membro.get("displayName") or "").upper()
        if any("AMANDA" in t.upper() for t in todas_tags):
            atend_id = "__tag_amanda__"
        elif "LARA" in nome_api:
            atend_id = "__tag_lara__"
        atendente = MEMBROS.get(atend_id, "Outros")

        resultado.append({
            "eh_novo":    eh_novo,
            "atendente":  atendente,
            "servico":    detectar_servico(todas_tags),
            "agendamento": detectar_agendamento(texto, todas_tags),
        })
    return resultado


# ─────────────────────────────────────────────
# MONTAGEM DA MENSAGEM
# ─────────────────────────────────────────────

def montar_mensagem(conversas, ontem_fmt):
    novos   = [c for c in conversas if c["eh_novo"]]
    agendados  = sum(1 for c in novos if c["agendamento"] == "agendou")
    cancelados = sum(1 for c in novos if c["agendamento"] == "cancelamento")
    total_novos = len(novos)
    taxa = round(agendados / total_novos * 100) if total_novos > 0 else 0

    # Especialidades dos novos
    ESPECIALIDADES = [
        ("Avaliação Neuropsicológica", "🧠", "Avaliação"),
        ("Psiquiatria",                "💊", "Psiquiatria"),
        ("Psicoterapia",               "🛋️", "Psicologia"),
    ]
    maior = max(len(label) for _, _, label in ESPECIALIDADES)
    linhas = ""
    for chave, emoji, label in ESPECIALIDADES:
        total = sum(1 for c in novos if c["servico"] == chave)
        agd   = sum(1 for c in novos if c["servico"] == chave and c["agendamento"] == "agendou")
        pontos  = "." * (maior - len(label) + 4)
        agd_txt = f" ({agd}✅)" if agd > 0 else ""
        linhas += f"{emoji} {label} {pontos} *{total}* leads{agd_txt}\n"

    # Atendentes (total do dia, não só novos)
    ATENDENTES = ["Amanda", "Ana", "Francine", "Lara"]
    partes = []
    for nome in ATENDENTES:
        t = sum(1 for c in conversas if c["atendente"] == nome)
        partes.append(f"{nome} *{t}*")
    linha_atend = " · ".join(partes)

    return (
        f"🏥 *Afetivamente — {ontem_fmt}*\n\n"
        f"┌ 📥 *{total_novos}* novos  📅 *{agendados}* agend.  ❌ *{cancelados}* cancel.\n"
        f"└ 📈 Taxa de conversão: *{taxa}%*\n\n"
        f"{linhas}\n"
        f"👥 {linha_atend}"
    )


# ─────────────────────────────────────────────
# ENVIO WHATSAPP
# ─────────────────────────────────────────────

def enviar(numero, mensagem):
    url     = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}/send-text"
    payload = json.dumps({"phone": numero, "message": mensagem}).encode()
    headers = {"Content-Type": "application/json"}
    if ZAPI_CLIENT_TOKEN:
        headers["Client-Token"] = ZAPI_CLIENT_TOKEN
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    ontem     = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    ontem_fmt = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
    print(f"📅 Buscando dados de {ontem}...")

    raw = umbler_get("chats", {"organizationId": UMBLER_ORG_ID, "take": 250})
    items = raw.get("items", [])

    # Filtra só conversas ativas ontem
    chats_ontem = [
        c for c in items
        if ((c.get("contact") or {}).get("lastActiveUTC") or
            c.get("eventAtUTC") or c.get("createdAtUTC") or "")[:10] == ontem
    ]
    print(f"✅ {len(chats_ontem)} conversas em {ontem}")

    conversas  = processar(chats_ontem, ontem)
    mensagem   = montar_mensagem(conversas, ontem_fmt)

    print("\n── Preview ──")
    print(mensagem)
    print("─────────────\n")

    ok = 0
    for numero in DESTINATARIOS:
        try:
            res = enviar(numero, mensagem)
            print(f"✅ Enviado para {numero}: {res.get('messageId','')}")
            ok += 1
        except Exception as e:
            print(f"❌ Falha para {numero}: {e}")

    print(f"\n{ok}/{len(DESTINATARIOS)} mensagem(ns) enviada(s).")


if __name__ == "__main__":
    main()
