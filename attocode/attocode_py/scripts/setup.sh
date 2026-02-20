#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
ALIAS_NAME="attocodepy"

echo "=== Attocode Python Setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# 1. Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "[1/4] Virtual environment already exists"
fi

# 2. Install with all extras
echo "[2/4] Installing attocode with dev + provider extras..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install -e "$PROJECT_DIR[dev,anthropic,openai,tree-sitter]"

# 3. Verify the entry point works
echo "[3/4] Verifying install..."
if "$VENV_DIR/bin/attocode" --version >/dev/null 2>&1; then
    VERSION=$("$VENV_DIR/bin/attocode" --version)
    echo "  $VERSION"
else
    echo "  WARNING: attocode --version failed, but install may still work"
fi

# 4. Set up shell alias
ATTOCODE_BIN="$VENV_DIR/bin/attocode"
echo "[4/4] Setting up '$ALIAS_NAME' alias..."

alias_line_bash="alias $ALIAS_NAME=\"$ATTOCODE_BIN\""
alias_line_fish="alias $ALIAS_NAME $ATTOCODE_BIN"

installed=false

# Fish
FISH_CONFIG="$HOME/.config/fish/config.fish"
if [ -f "$FISH_CONFIG" ]; then
    if ! grep -qF "$ALIAS_NAME" "$FISH_CONFIG" 2>/dev/null; then
        echo "" >> "$FISH_CONFIG"
        echo "# Attocode Python agent" >> "$FISH_CONFIG"
        echo "$alias_line_fish" >> "$FISH_CONFIG"
        echo "  Added to $FISH_CONFIG"
        installed=true
    else
        echo "  Already in $FISH_CONFIG"
        installed=true
    fi
fi

# Zsh
ZSHRC="$HOME/.zshrc"
if [ -f "$ZSHRC" ]; then
    if ! grep -qF "$ALIAS_NAME" "$ZSHRC" 2>/dev/null; then
        echo "" >> "$ZSHRC"
        echo "# Attocode Python agent" >> "$ZSHRC"
        echo "$alias_line_bash" >> "$ZSHRC"
        echo "  Added to $ZSHRC"
        installed=true
    else
        echo "  Already in $ZSHRC"
        installed=true
    fi
fi

# Bash
BASHRC="$HOME/.bashrc"
if [ -f "$BASHRC" ]; then
    if ! grep -qF "$ALIAS_NAME" "$BASHRC" 2>/dev/null; then
        echo "" >> "$BASHRC"
        echo "# Attocode Python agent" >> "$BASHRC"
        echo "$alias_line_bash" >> "$BASHRC"
        echo "  Added to $BASHRC"
        installed=true
    else
        echo "  Already in $BASHRC"
        installed=true
    fi
fi

if [ "$installed" = false ]; then
    echo "  No shell config found. Add manually:"
    echo "    bash/zsh: $alias_line_bash"
    echo "    fish:     $alias_line_fish"
fi

echo ""
echo "=== Done ==="
echo "Restart your shell (or source your config), then run:"
echo "  $ALIAS_NAME              # interactive TUI"
echo "  $ALIAS_NAME \"prompt\"     # single-turn"
