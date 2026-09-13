#!/data/data/com.termux/files/usr/bin/bash

set -e

INSTALL_DIR="$HOME/.zd_tool"
RAW_URL="https://raw.githubusercontent.com/USERNAME/ZD-TOOL/main/zone.py"

mkdir -p "$INSTALL_DIR"

echo "[*] Downloading ZD_TOOL..."

curl -L "$RAW_URL" -o "$INSTALL_DIR/zone.py"

cat > "$PREFIX/bin/ZD_TOOL" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
python "$HOME/.zd_tool/zone.py"
EOF

chmod +x "$PREFIX/bin/ZD_TOOL"

cat > "$PREFIX/bin/ZD_TOOL_UPDATE" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash

INSTALL_DIR="$HOME/.zd_tool"
RAW_URL="https://raw.githubusercontent.com/USERNAME/ZD-TOOL/main/zone.py"

echo "[*] Updating ZD_TOOL..."

curl -L "$RAW_URL" -o "$INSTALL_DIR/zone.py"

echo "[+] ZD_TOOL updated."
EOF

chmod +x "$PREFIX/bin/ZD_TOOL_UPDATE"

echo
echo "[+] Installation complete!"
echo
echo "Run:"
echo "  ZD_TOOL"
echo
echo "Update:"
echo "  ZD_TOOL_UPDATE"