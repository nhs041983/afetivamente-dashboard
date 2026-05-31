#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# Instala o agendamento diário às 08:00 no macOS (launchd)
# Execute UMA VEZ: bash agendar_relatorio.sh
# ─────────────────────────────────────────────────────────────────

PLIST="$HOME/Library/LaunchAgents/com.afetivamente.relatorio.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$(dirname "$SCRIPT_DIR")/.env"

echo "📋 Criando agendamento em: $PLIST"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.afetivamente.relatorio</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>source "$ENV_FILE" 2>/dev/null; /usr/bin/python3 "$SCRIPT_DIR/relatorio.py" >> "$SCRIPT_DIR/relatorio.log" 2>&1</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>$SCRIPT_DIR/relatorio.log</string>
  <key>StandardErrorPath</key>
  <string>$SCRIPT_DIR/relatorio.log</string>
</dict>
</plist>
EOF

# Carrega o agendamento
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST"

echo "✅ Agendado! O relatório será enviado todo dia às 08:00."
echo "📄 Logs em: $SCRIPT_DIR/relatorio.log"
echo ""
echo "Para testar agora (sem esperar as 08h):"
echo "  python3 $SCRIPT_DIR/relatorio.py"
echo ""
echo "Para cancelar o agendamento:"
echo "  launchctl unload $PLIST"
