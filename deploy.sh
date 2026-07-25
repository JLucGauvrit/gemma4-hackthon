#!/usr/bin/env bash
# Deploy Devil's Advocates to a fresh GPU box.  usage: ./deploy.sh user@host [port]
# Assumes: Ubuntu-ish, an NVIDIA GPU, and that you can already `ssh user@host`.
set -euo pipefail

TARGET="${1:?usage: ./deploy.sh user@host [port]}"
PORT="${2:-8765}"

[ -d "$HOME/.devils_advocates" ] || {
  echo "no OpenAIRE tokens locally. run this first, it opens a browser:"
  echo "  uv run python -m core.mcp_client openaire"
  exit 1
}

# Ships the working tree as-is, not a named branch — check out what you mean to
# deploy before running. Printed so it's never a guess.
echo "==> shipping $(git branch --show-current) @ $(git rev-parse --short HEAD)$(git diff --quiet || echo ' + uncommitted changes') to $TARGET"
# ponytail: rsync over git clone — dodges private-repo auth on the box, and
# carries the OAuth tokens in the same step. Switch to git if you need history.
rsync -az --delete \
  --exclude .venv --exclude .git --exclude __pycache__ --exclude '*.pyc' \
  ./ "$TARGET:~/devils-advocates/"
rsync -az ~/.devils_advocates/ "$TARGET:~/.devils_advocates/"

echo "==> setting up box (models are the slow part, ~5-15 min)"
ssh "$TARGET" PORT="$PORT" 'bash -s' <<'REMOTE'
set -euo pipefail
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
command -v uv     >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

pgrep -x ollama >/dev/null || { nohup ollama serve >~/ollama.log 2>&1 & sleep 5; }
ollama pull gemma4:e4b
ollama pull gemma4:e2b

cd ~/devils-advocates
uv sync
pkill -f 'api.server' || true
# ponytail: nohup, not systemd. It's a hackathon demo, not a service.
# If it needs to survive reboots, make it a systemd unit then.
nohup uv run python -m api.server --host 0.0.0.0 --port "$PORT" >~/server.log 2>&1 &
sleep 5
curl -sf "http://127.0.0.1:$PORT/" >/dev/null && echo "server up on :$PORT" || {
  echo "server did not come up. logs:"; tail -30 ~/server.log; exit 1; }
REMOTE

IP="${TARGET#*@}"
echo
echo "done ->  http://$IP:$PORT"
echo "open port $PORT in the provider's firewall/security group or nobody can reach it."
echo "logs:  ssh $TARGET tail -f server.log"
