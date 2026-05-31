#!/bin/bash
cd "$(dirname "$0")"

export $(cat .env | xargs)

echo "🚀 Iniciando Dashboard Afetivamente..."
echo "📊 Acesse: http://localhost:8765"
echo ""
echo "Pressione Ctrl+C para parar."
echo ""

python3 backend/app.py
