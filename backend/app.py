import os
import json
import time
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from collections import Counter

# Cache em memória: evita rebuscar 250 conversas a cada clique
_cache = {"dados": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutos

def cache_get():
    if _cache["dados"] and (time.time() - _cache["timestamp"]) < CACHE_TTL:
        return _cache["dados"]
    return None

def cache_set(dados):
    _cache["dados"] = dados
    _cache["timestamp"] = time.time()

TOKEN   = os.environ.get("UMBLER_TOKEN", "")
ORG_ID  = os.environ.get("UMBLER_ORG_ID", "aGUzJJk5JQhSWCnw")
BASE_URL = "https://app-utalk.umbler.com/api/v1"

MEMBROS_FILE = os.path.join(os.path.dirname(__file__), "../membros.json")

# ── Palavras-chave por categoria ──────────────────────────────────────────────
KW_SERVICOS = {
    "Avaliação Neuropsicológica":["avaliação neuropsicológica","avaliacao neuropsicologica","neuropsicológica","neuropsicologica",
                                  "tdah","autismo","tea","dislexia","laudo","avaliação cognitiva","neuropsi","avaliação neuro",
                                  "avaliação é realizada","pacote único","pacote unico","sessões de avaliação"],
    "Psicoterapia":              ["psicoterapia","terapia","terapeuta","psicólogo","psicologa","psicóloga","psicólogos",
                                  "sessão de terapia","sessao de terapia","atendimento psicológico","sessões de psicoterapia"],
    "Psiquiatria":               ["psiquiatria","psiquiatra","psiquiátrico","medicação","medicamento","remédio","remedio",
                                  "laudo psiquiátrico","receita","consulta psiquiátrica","dr. leandro","dr leandro"],
    "Acolhimento":               ["acolhimento","acolher","primeira vez","começar","iniciar tratamento","quero começar"],
}

KW_SEM_RESPOSTA = ["lead sem resposta"]

KW_AGENDOU = [
    "agendado","agendamos","agendei","consulta confirmada","confirmado","confirmada",
    "marcado","marcamos","marcamos","horário confirmado","horario confirmado",
    "consulta marcada","vou comparecer","estarei lá","estarei la","até lá","ate la",
    "boa tarde!! tudo bem","confirmado ✓",
]
KW_CANCELAMENTO = [
    "cancelar","cancelamento","cancelei","cancela","desistir","desistência",
    "não quero mais","nao quero mais","encerrar","desmarcar","desmarcei",
    "não vou mais","nao vou mais","não consigo ir","nao consigo ir",
]
KW_PERDIDO = [
    "muito caro","não tenho dinheiro","nao tenho dinheiro","sem condições","sem condicoes",
    "vou pensar","depois vejo","outra hora","não tenho como","nao tenho como",
    "não posso agora","nao posso agora","infelizmente não","infelizmente nao",
]
KW_LEAD = [
    "quero agendar","gostaria de agendar","como funciona","quanto custa","qual o valor",
    "quais são os valores","valores","preço","preco","informações","informacoes",
    "gostaria de saber","tem disponibilidade","tem horário","tem horario",
    "como faço","como faco","preciso de ajuda","preciso de um","estou buscando",
    "estou procurando","tem psicólogo","tem psicologa","tem psiquiatra",
]

def carregar_membros():
    try:
        with open(MEMBROS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def nome_membro(mid, membros):
    return membros.get(mid, mid[:8] + "..." if mid else "Sem atendente")

def umbler_get(path, params=None):
    url = f"{BASE_URL}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def extrair_texto(chat):
    """Extrai todo o texto disponível do chat (última mensagem + histórico de atividade)."""
    partes = []
    msg = chat.get("lastMessage") or {}
    partes.append(msg.get("content") or msg.get("text") or "")
    # firstContactMessage e firstMemberReplyMessage ficam no histórico — sem texto extra disponível via lista
    return " ".join(partes).lower()

TAG_PARA_SERVICO = {
    "AVALIAÇÃO NEUROPSICOLÓGICA": "Avaliação Neuropsicológica",
    "PSICOTERAPIA":               "Psicoterapia",
    "PSIQUIATRIA":                "Psiquiatria",
    "ACOLHIMENTO":                "Acolhimento",
    "FONOAUDIÓLOGA":              "Fonoaudiologia",
    "FONOAUDIOLOGIA":             "Fonoaudiologia",
    "NUTRICIONISTA":              "Nutrição",
    "MED FAMÍLIA":                "Medicina de Família",
}

TAG_PARA_PAGAMENTO = {
    "PARTICULAR":      "Particular",
    "PLANO DE SAÚDE":  "Plano de Saúde",
    "CASSI":           "CASSI",
    "PREFEITURAS":     "Prefeitura",
    "HOSPITALAR":      "Hospitalar",
}

TAG_PIPELINE = {
    "NEGOCIANDO":        "negociando",
    "LEAD SEM RESPOSTA": "sem_resposta",
    "NÃO RESPONDEU":     "sem_resposta",
    "NAO RESPONDEU":     "sem_resposta",
    "NÃO RESPONDEU":     "sem_resposta",
    "RETOMAR CONVERSA":  "retomar",
    "Não Respondeu".upper(): "sem_resposta",
}

TAG_PERFIL = {
    "PAIS DE PACIENTE": "Pais de Paciente",
    "PROFISSIONAIS":    "Profissional de Saúde",
    "FORNECEDOR":       "Fornecedor",
}

def detectar_servicos(texto, tags):
    encontrados = []
    tags_upper = [t.upper().strip() for t in tags]

    # 1. Tags têm prioridade máxima — são explícitas
    for tag_u in tags_upper:
        for tag_key, servico in TAG_PARA_SERVICO.items():
            if tag_key in tag_u and servico not in encontrados:
                encontrados.append(servico)

    # 2. Complementa com análise de texto apenas se nenhuma tag de serviço foi encontrada
    if not encontrados:
        for servico, palavras in KW_SERVICOS.items():
            if any(p in texto for p in palavras):
                encontrados.append(servico)

    return encontrados or ["Não identificado"]

def detectar_agendamento(texto, tags):
    todas_tags = " ".join(tags).upper()
    if "EM ATENDIMENTO" in todas_tags or any(k in texto for k in KW_AGENDOU):
        return "agendou"
    if any(k in texto for k in KW_CANCELAMENTO):
        return "cancelamento"
    if "NOVO LEAD" in todas_tags or any(k in texto for k in KW_LEAD):
        return "nao_agendou"
    return "indefinido"

def detectar_status(texto, tags, status_api):
    todas_tags = " ".join(tags).upper()
    if status_api in ["Resolved", "Closed"]:
        return "resolvido"
    if any(k in texto for k in KW_CANCELAMENTO) or "CANCELAMENTO" in todas_tags:
        return "cancelamento"
    if any(k in texto for k in KW_PERDIDO):
        return "perdido"
    if "NOVO LEAD" in todas_tags or any(k in texto for k in KW_LEAD):
        return "lead"
    if any(k in texto for k in KW_AGENDOU) or "EM ATENDIMENTO" in todas_tags:
        return "em_atendimento"
    return "em_atendimento"

def buscar_conversas(data_inicio=None, data_fim=None):
    raw = cache_get()
    if raw is None:
        params = {"organizationId": ORG_ID, "take": 250}
        raw = umbler_get("chats", params)
        if "error" not in raw:
            cache_set(raw)

    if "error" in raw:
        return raw

    if not data_inicio:
        return raw

    d_ini = data_inicio[:10]
    d_fim = (data_fim or "9999-12-31")[:10]

    # Retorna TODOS que foram ativos OU criados no período
    # A separação é feita no processamento
    filtrados = [
        c for c in raw.get("items", [])
        if d_ini <= (
            (c.get("contact") or {}).get("lastActiveUTC") or
            c.get("eventAtUTC") or
            c.get("createdAtUTC") or ""
        )[:10] <= d_fim
    ]
    resultado = dict(raw)
    resultado["items"] = filtrados
    resultado["d_ini"] = d_ini
    resultado["d_fim"] = d_fim
    return resultado

def processar_conversas(chats, membros):
    resultado = []
    for c in chats:
        contato    = c.get("contact") or {}
        membro     = c.get("organizationMember") or {}
        status_api = c.get("status", "")

        tags_contato = [t.get("name", "") for t in (contato.get("tags") or [])]
        tags_chat    = [t.get("name", "") for t in (c.get("tags") or [])]
        todas_tags   = tags_contato + tags_chat

        texto = extrair_texto(c)

        status     = detectar_status(texto, todas_tags, status_api)
        agendamento = detectar_agendamento(texto, todas_tags)
        servicos   = detectar_servicos(texto, todas_tags)
        data_conv  = (
            (contato.get("lastActiveUTC") or c.get("eventAtUTC") or c.get("createdAtUTC") or "")
        )[:10]

        msg = c.get("lastMessage") or {}
        ultima_msg = (msg.get("content") or msg.get("text") or "")[:120]

        data_criacao = (c.get("createdAtUTC") or "")[:10]
        sem_resposta = any(t.upper() in ("LEAD SEM RESPOSTA","NÃO RESPONDEU","NAO RESPONDEU","NÃO RESPONDEU") for t in todas_tags)

        # Detectar atendente: começa pelo ID
        atendente_id_final = membro.get("id", "")

        # Amanda detectada pela tag
        if any("AMANDA" in t.upper() for t in todas_tags):
            atendente_id_final = "__tag_amanda__"

        # Lara compartilha login com Ana — detectar pelo nome exibido na API
        nome_api = (membro.get("name") or membro.get("displayName") or "").strip()
        if "LARA" in nome_api.upper():
            atendente_id_final = "__tag_lara__"

        # Pagamento
        pagamento = "Não informado"
        for t in todas_tags:
            p = TAG_PARA_PAGAMENTO.get(t.upper().strip())
            if p:
                pagamento = p
                break

        # Pipeline
        pipeline = "normal"
        for t in todas_tags:
            pp = TAG_PIPELINE.get(t.upper().strip())
            if pp:
                pipeline = pp
                break

        # Perfil do cliente
        perfil = "Paciente"
        for t in todas_tags:
            pf = TAG_PERFIL.get(t.upper().strip())
            if pf:
                perfil = pf
                break

        resultado.append({
            "id":               c.get("id", ""),
            "contato":          contato.get("name") or contato.get("phoneNumber") or "Desconhecido",
            "telefone":         contato.get("phoneNumber", ""),
            "atendente_id":     atendente_id_final,
            "atendente_nome":   nome_membro(atendente_id_final, membros),
            "pagamento":        pagamento,
            "pipeline":         pipeline,
            "perfil":           perfil,
            "data_criacao":     data_criacao,
            "eh_novo":          False,  # preenchido depois com d_ini
            "status":           status,
            "agendamento":      agendamento,
            "servicos":         servicos,
            "sem_resposta":     sem_resposta,
            "ultima_mensagem":  ultima_msg,
            "ultima_atividade": contato.get("lastActiveUTC", ""),
            "data":             data_conv,
            "tags":             todas_tags,
        })
    return resultado

def gerar_resumo(conversas, d_ini=""):
    total = len(conversas)
    por_status    = {"lead": 0, "cancelamento": 0, "perdido": 0, "resolvido": 0, "em_atendimento": 0}
    por_atendente = {}
    por_dia       = {}
    por_servico   = Counter()
    agendamentos  = {"agendou": 0, "nao_agendou": 0, "cancelamento": 0, "indefinido": 0}
    funil_servico = {}
    sem_resposta_total = 0
    por_pagamento  = Counter()
    por_pipeline   = Counter()
    por_perfil     = Counter()
    novos = []      # criados no período
    ativos = []     # ativos no período mas criados antes

    for c in conversas:
        s = c["status"]
        por_status[s] = por_status.get(s, 0) + 1

        nome = c["atendente_nome"]
        if nome not in por_atendente:
            por_atendente[nome] = {"total": 0, "lead": 0, "cancelamento": 0, "perdido": 0,
                                   "resolvido": 0, "em_atendimento": 0, "agendou": 0, "nao_agendou": 0}
        por_atendente[nome]["total"] += 1
        por_atendente[nome][s] = por_atendente[nome].get(s, 0) + 1
        ag = c["agendamento"]
        if ag in por_atendente[nome]:
            por_atendente[nome][ag] += 1

        dia = c["data"]
        if dia:
            por_dia[dia] = por_dia.get(dia, 0) + 1

        for sv in c["servicos"]:
            por_servico[sv] += 1

        agendamentos[ag] = agendamentos.get(ag, 0) + 1

        if c.get("sem_resposta"):
            sem_resposta_total += 1

        por_pagamento[c.get("pagamento", "Não informado")] += 1
        por_pipeline[c.get("pipeline", "normal")] += 1
        por_perfil[c.get("perfil", "Paciente")] += 1

        dc = c.get("data_criacao", "")
        if d_ini and dc >= d_ini:
            novos.append(c)
        else:
            ativos.append(c)

        for sv in c["servicos"]:
            if sv not in funil_servico:
                funil_servico[sv] = {"total": 0, "agendou": 0, "nao_agendou": 0, "cancelamento": 0, "sem_resposta": 0}
            funil_servico[sv]["total"] += 1
            if ag == "agendou":
                funil_servico[sv]["agendou"] += 1
            elif ag == "nao_agendou":
                funil_servico[sv]["nao_agendou"] += 1
            elif c["status"] == "cancelamento":
                funil_servico[sv]["cancelamento"] += 1
            if c.get("sem_resposta"):
                funil_servico[sv]["sem_resposta"] += 1

    return {
        "total":            total,
        "por_status":       por_status,
        "por_atendente":    por_atendente,
        "por_dia":          dict(sorted(por_dia.items())),
        "por_servico":      dict(por_servico.most_common()),
        "agendamentos":     agendamentos,
        "taxa_conversao":    round((por_status["resolvido"] / total * 100) if total > 0 else 0, 1),
        "taxa_agendamento":  round((agendamentos["agendou"] / total * 100) if total > 0 else 0, 1),
        "funil_servico":      dict(sorted(funil_servico.items(), key=lambda x: x[1]["total"], reverse=True)),
        "sem_resposta_total": sem_resposta_total,
        "por_pagamento":      dict(por_pagamento.most_common()),
        "por_pipeline":       dict(por_pipeline.most_common()),
        "por_perfil":         dict(por_perfil.most_common()),
        "total_novos":        len(novos),
        "total_ativos":       len(ativos),
        "novos_por_servico":  dict(Counter(sv for c in novos for sv in c["servicos"]).most_common()),
        "ativos_por_servico": dict(Counter(sv for c in ativos for sv in c["servicos"]).most_common()),
        "novos_agendamentos": sum(1 for c in novos if c["agendamento"] == "agendou"),
        "ativos_agendamentos": sum(1 for c in ativos if c["agendamento"] == "agendou"),
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            with open(os.path.join(os.path.dirname(__file__), "../frontend/index.html"), "rb") as f:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f.read())

        elif parsed.path == "/api/dashboard":
            data_inicio = (params.get("data_inicio") or params.get("inicio") or [None])[0]
            data_fim    = (params.get("data_fim")    or params.get("fim")    or [None])[0]
            forcar      = params.get("forcar", [None])[0]

            if forcar:
                cache_set(None); _cache["dados"] = None

            raw = buscar_conversas(data_inicio, data_fim)
            if "error" in raw:
                self.send_json({"erro": raw["error"]}, 500)
                return

            membros   = carregar_membros()
            d_ini_val = raw.get("d_ini", "")
            conversas = processar_conversas(raw.get("items", []), membros)
            # Marcar quais são novos
            for c in conversas:
                c["eh_novo"] = bool(d_ini_val and c.get("data_criacao","") >= d_ini_val)
            resumo    = gerar_resumo(conversas, d_ini_val)
            self.send_json({"resumo": resumo, "conversas": conversas})

        else:
            self.send_json({"erro": "Rota não encontrada"}, 404)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

if __name__ == "__main__":
    porta = 8765
    print(f"✅ Dashboard rodando em http://localhost:{porta}")
    ThreadedHTTPServer(("localhost", porta), Handler).serve_forever()
