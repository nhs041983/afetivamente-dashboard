#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# Adiciona as credenciais Z-API ao .env do projeto
# Execute: bash configurar_zapi.sh
# ─────────────────────────────────────────────────────────────────

ENV_FILE="$(dirname "$(dirname "$(cd "$(dirname "$0")" && pwd)")")/Dashboard/.env"

echo "🔧 Configuração Z-API — Afetivamente"
echo ""
echo "Acesse: https://app.z-api.io → sua instância → 'Credenciais'"
echo ""

read -p "Cole seu Instance ID (ex: 3ABC1234DEFG): " INSTANCE
read -p "Cole seu Token (ex: abc123xyz...): " TOKEN
read -p "Cole seu Client-Token (Security Token do painel): " CLIENT_TOKEN
echo ""
read -p "Número do Nasser (55 + DDD + número, sem espaço): " NUM_NASSER

echo "" >> "$ENV_FILE"
echo "# Z-API WhatsApp" >> "$ENV_FILE"
echo "ZAPI_INSTANCE=$INSTANCE" >> "$ENV_FILE"
echo "ZAPI_TOKEN=$TOKEN" >> "$ENV_FILE"
echo "ZAPI_CLIENT_TOKEN=$CLIENT_TOKEN" >> "$ENV_FILE"
echo "WHATS_NASSER=$NUM_NASSER" >> "$ENV_FILE"

echo "✅ Credenciais salvas em .env"
echo ""
echo "Para adicionar mais destinatários, edite o arquivo:"
echo "  Dashboard/relatorio_diario/relatorio.py"
echo "  → seção DESTINATARIOS"
