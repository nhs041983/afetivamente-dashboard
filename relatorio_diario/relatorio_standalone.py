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


def processar(chats, periodo_ini, periodo_fim=None):
    """periodo_ini: data início do período. eh_novo = criado dentro do período."""
    if periodo_fim is None:
        periodo_fim = periodo_ini
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
        eh_novo      = periodo_ini <= data_criacao <= periodo_fim

        # Ignorar contatos que não são leads (currículo, serviço indisponível, parceiros)
        tags_upper = [t.upper().strip() for t in todas_tags]
        NAO_LEADS = {"CURRÍCULOS", "CURRICULOS", "SERVIÇO NÃO DISPONÍVEL",
                     "SERVICO NAO DISPONIVEL", "PROFISSIONAIS PARCEIROS"}
        if any(t in NAO_LEADS for t in tags_upper):
            eh_novo = False  # não conta nas métricas de conversão

        # Aguardando resposta
        sem_resposta = any(t in tags_upper for t in [
            "LEAD SEM RESPOSTA", "NÃO RESPONDEU", "NAO RESPONDEU", "RETOMAR CONVERSA"
        ])

        # Atendente — ID da API tem prioridade
        atend_id = membro.get("id", "")
        nome_api = (membro.get("name") or membro.get("displayName") or "").upper()

        if atend_id and atend_id in MEMBROS:
            # Atendente identificado pelo ID — só verifica Lara (mesmo login que Ana)
            if "LARA" in nome_api:
                atend_id = "__tag_lara__"
        else:
            # Sem atendente atribuído — detecta Amanda pela tag
            if any("AMANDA" in t.upper() for t in todas_tags):
                atend_id = "__tag_amanda__"

        atendente = MEMBROS.get(atend_id, "Outros")

        resultado.append({
            "eh_novo":      eh_novo,
            "sem_resposta": sem_resposta,
            "atendente":  atendente,
            "servico":    detectar_servico(todas_tags),
            "agendamento": detectar_agendamento(texto, todas_tags),
        })
    return resultado


# ─────────────────────────────────────────────
# MONTAGEM DA MENSAGEM
# ─────────────────────────────────────────────

def calcular_taxa(conversas):
    """Taxa de conversão de leads novos para agendamentos."""
    novos = [c for c in conversas if c["eh_novo"]]
    agend = sum(1 for c in novos if c["agendamento"] == "agendou")
    return len(novos), agend, round(agend / len(novos) * 100) if novos else 0


def montar_mensagem(conversas_ontem, conversas_semana, conversas_mes, ontem_fmt):
    # ── Dados do dia ──
    novos_dia   = [c for c in conversas_ontem if c["eh_novo"]]
    agend_dia   = sum(1 for c in novos_dia if c["agendamento"] == "agendou")
    cancel_dia  = sum(1 for c in novos_dia if c["agendamento"] == "cancelamento")
    total_dia   = len(novos_dia)
    taxa_dia    = round(agend_dia / total_dia * 100) if total_dia else 0

    # ── Taxa semana e mês ──
    _, agend_sem, taxa_sem = calcular_taxa(conversas_semana)
    tot_sem = sum(1 for c in conversas_semana if c["eh_novo"])

    _, agend_mes, taxa_mes = calcular_taxa(conversas_mes)
    tot_mes = sum(1 for c in conversas_mes if c["eh_novo"])

    # ── Especialidades do dia ──
    ESPECIALIDADES = [
        ("Avaliação Neuropsicológica", "🧠", "Avaliação"),
        ("Psiquiatria",                "💊", "Psiquiatria"),
        ("Psicoterapia",               "🛋️", "Psicologia"),
    ]
    maior = max(len(label) for _, _, label in ESPECIALIDADES)
    linhas_serv = ""
    for chave, emoji, label in ESPECIALIDADES:
        total = sum(1 for c in novos_dia if c["servico"] == chave)
        agd   = sum(1 for c in novos_dia if c["servico"] == chave and c["agendamento"] == "agendou")
        pontos  = "." * (maior - len(label) + 4)
        agd_txt = f" ({agd}✅)" if agd > 0 else ""
        linhas_serv += f"{emoji} {label} {pontos} *{total}* leads{agd_txt}\n"

    # ── Especialidade com maior abandono (mês) ──
    abandono = {}
    for chave, _, label in ESPECIALIDADES:
        total = sum(1 for c in conversas_mes if c["eh_novo"] and c["servico"] == chave)
        agd   = sum(1 for c in conversas_mes if c["eh_novo"] and c["servico"] == chave and c["agendamento"] == "agendou")
        perdidos = total - agd
        if total > 0:
            abandono[label] = (perdidos, total)
    pior_serv = max(abandono, key=lambda x: abandono[x][0]) if abandono else None
    linha_abandono = ""
    if pior_serv:
        perd, tot = abandono[pior_serv]
        linha_abandono = f"  ⚠️ Abandono: *{pior_serv}* · {perd}/{tot}\n"

    # ── Taxa por atendente (mês) ──
    ATENDENTES = ["Amanda", "Ana", "Francine", "Lara"]
    linhas_atend = ""
    for nome in ATENDENTES:
        novos_a = [c for c in conversas_mes if c["eh_novo"] and c["atendente"] == nome]
        agend_a = sum(1 for c in novos_a if c["agendamento"] == "agendou")
        taxa_a  = round(agend_a / len(novos_a) * 100) if novos_a else 0
        conv_dia_a = sum(1 for c in conversas_ontem if c["atendente"] == nome)
        linhas_atend += f"  {nome}: *{conv_dia_a}* conv. hoje · *{taxa_a}%* conv./mês\n"

    # ── Leads perdidos no mês ──
    perdidos_mes = sum(
        1 for c in conversas_mes
        if c["eh_novo"] and c["agendamento"] not in ("agendou",)
    )

    # Data formatada por extenso
    meses = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    d = datetime.now() - timedelta(days=1)
    data_ext = f"{d.day} {meses[d.month-1]} {d.year}"

    # Equipe comercial — só quem fecha (Francine, Ana, Lara)
    COMERCIAL = ["Francine", "Ana", "Lara"]
    linhas_atend = ""
    for nome in COMERCIAL:
        novos_a  = [c for c in conversas_mes if c["eh_novo"] and c["atendente"] == nome]
        agend_a  = sum(1 for c in novos_a if c["agendamento"] == "agendou")
        taxa_a   = round(agend_a / len(novos_a) * 100) if novos_a else 0
        conv_dia = sum(1 for c in conversas_ontem if c["atendente"] == nome)
        linhas_atend += f"  *{nome}* — {conv_dia} hoje · {taxa_a}% mês\n"

    # Amanda (IA) — só volume, sem conversão
    amanda_dia = sum(1 for c in conversas_ontem if c["atendente"] == "Amanda")
    amanda_mes = sum(1 for c in conversas_mes if c["atendente"] == "Amanda")

    return (
        f"🏥 *AFETIVAMENTE* · _{data_ext}_\n\n"
        f"*HOJE*\n"
        f"  Leads · *{total_dia}*\n"
        f"  Agendamentos · *{agend_dia}*\n"
        f"  Cancelamentos · *{cancel_dia}*\n"
        f"  Conversão · *{taxa_dia}%*\n\n"
        f"*ESPECIALIDADES*\n"
        f"{linhas_serv}\n"
        f"*CONVERSÃO*\n"
        f"  7 dias · *{taxa_sem}%* ({agend_sem}/{tot_sem})\n"
        f"  30 dias · *{taxa_mes}%* ({agend_mes}/{tot_mes})\n"
        f"  Perdidos · *{perdidos_mes}*\n\n"
        f"*AGUARDANDO RESPOSTA*\n"
        f"  7 dias · *{sum(1 for c in conversas_semana if c.get('sem_resposta'))}* contatos\n"
        f"  30 dias · *{sum(1 for c in conversas_mes if c.get('sem_resposta'))}* contatos\n\n"
        f"*EQUIPE COMERCIAL*\n"
        f"{linhas_atend}"
        f"  🤖 Amanda (IA) · *{amanda_dia}* conversas hoje\n"
        f"{linha_abandono}\n"
        f"_Setor Comercial — dia anterior_"
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

def filtrar_por_periodo(items, d_ini, d_fim):
    return [
        c for c in items
        if d_ini <= ((c.get("contact") or {}).get("lastActiveUTC") or
                     c.get("eventAtUTC") or c.get("createdAtUTC") or "")[:10] <= d_fim
    ]


def main():
    hoje      = datetime.now()
    ontem     = (hoje - timedelta(days=1)).strftime("%Y-%m-%d")
    ontem_fmt = (hoje - timedelta(days=1)).strftime("%d/%m/%Y")
    sem_ini   = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
    mes_ini   = (hoje - timedelta(days=30)).strftime("%Y-%m-%d")

    print(f"📅 Buscando dados...")
    raw   = umbler_get("chats", {"organizationId": UMBLER_ORG_ID, "take": 250})
    items = raw.get("items", [])

    chats_ontem  = filtrar_por_periodo(items, ontem, ontem)
    chats_semana = filtrar_por_periodo(items, sem_ini, ontem)
    chats_mes    = filtrar_por_periodo(items, mes_ini, ontem)

    print(f"✅ Hoje: {len(chats_ontem)} | Semana: {len(chats_semana)} | Mês: {len(chats_mes)}")

    conv_ontem  = processar(chats_ontem,  ontem,   ontem)
    conv_semana = processar(chats_semana, sem_ini, ontem)
    conv_mes    = processar(chats_mes,    mes_ini, ontem)

    mensagem = montar_mensagem(conv_ontem, conv_semana, conv_mes, ontem_fmt)

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
