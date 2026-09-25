#!/usr/bin/env bash
# Ship the current working tree to the EC2 server created by infra/ and (re)start the stack.
#
#   ./deploy/deploy.sh            # build + deploy
#   ./deploy/deploy.sh --logs     # then follow logs
#
# Needs: terraform outputs from infra/, ssh, tar, python3/python.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env.production"
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null && "$candidate" -c "import sys" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || { echo "Python 3 is required" >&2; exit 1; }

tf() { terraform -chdir="$ROOT/infra" output -raw "$1"; }
IP="$(tf public_ip)"
KEY="$ROOT/infra/$(basename "$(tf ssh_key_path)")"
REGION="$(tf region)"
LOG_GROUP="$(tf log_group)"

# OpenSSH on Windows refuses keys that other users can read.
if command -v icacls >/dev/null 2>&1; then
  icacls "$(cygpath -w "$KEY" 2>/dev/null || echo "$KEY")" /inheritance:r /grant:r "$(whoami):R" >/dev/null
else
  chmod 600 "$KEY"
fi
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=30 "ubuntu@$IP")

# ---------------------------------------------------------------- secrets
if [ ! -f "$ENV_FILE" ]; then
  echo "Creating $ENV_FILE with random secrets"
  "$PY" - "$ENV_FILE" <<'PY'
import secrets, sys
from pathlib import Path
tpl = Path(sys.argv[1]).with_name(".env.production.example").read_text()
values = {
    "SECRET_KEY": secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": secrets.token_hex(24),
    "ADMIN_PASSWORD": secrets.token_urlsafe(18),
}
lines = []
for line in tpl.splitlines():
    key = line.split("=", 1)[0]
    lines.append(f"{key}={values[key]}" if key in values else line.split("  #")[0].rstrip() if "=" in line and not line.startswith("#") else line)
Path(sys.argv[1]).write_text("\n".join(lines) + "\n")
PY
  echo "  -> set ADMIN_EMAIL and ANTHROPIC_API_KEY in deploy/.env.production, then re-run."
  exit 1
fi

# ---------------------------------------------------------------- wait for first boot
echo "Waiting for $IP to finish first-boot setup..."
for _ in $(seq 1 60); do
  if "${SSH[@]}" test -f /var/lib/cloud/instance/talentflow-ready 2>/dev/null; then break; fi
  sleep 10
done
"${SSH[@]}" test -f /var/lib/cloud/instance/talentflow-ready

# ---------------------------------------------------------------- upload
echo "Uploading source..."
tar -C "$ROOT" -czf - \
  --exclude=node_modules --exclude=.venv --exclude=.git --exclude='__pycache__' --exclude='*.db' --exclude='*.db-*' \
  --exclude=frontend/dist --exclude=backend/static --exclude=infra --exclude=deploy/.env.production . \
  | "${SSH[@]}" "mkdir -p /opt/talentflow && tar -C /opt/talentflow -xzf -"
{
  cat "$ENV_FILE"
  echo
  echo "AWS_REGION=$REGION"
  echo "LOG_GROUP=$LOG_GROUP"
} | "${SSH[@]}" "umask 077 && cat > /opt/talentflow/deploy/.env.production && ln -sf .env.production /opt/talentflow/deploy/.env"
# (deploy/.env lets plain `docker compose -f deploy/docker-compose.prod.yml ...` commands work on the server.)

# ---------------------------------------------------------------- build + start
echo "Building and starting containers (first build takes a few minutes)..."
"${SSH[@]}" "cd /opt/talentflow && docker compose -f deploy/docker-compose.prod.yml -f deploy/docker-compose.aws.yml \
  --env-file deploy/.env.production up -d --build --remove-orphans && docker image prune -f >/dev/null"

echo "Waiting for the app to become ready..."
for _ in $(seq 1 60); do
  if curl -fsS "http://$IP/api/ready" >/dev/null 2>&1; then
    echo "TalentFlow is live at http://$IP"
    [ "${1:-}" = "--logs" ] && exec "${SSH[@]}" "cd /opt/talentflow && docker compose -f deploy/docker-compose.prod.yml logs -f --tail=100"
    exit 0
  fi
  sleep 5
done
echo "App did not become ready; recent logs:" >&2
"${SSH[@]}" "cd /opt/talentflow && docker compose -f deploy/docker-compose.prod.yml ps && docker compose -f deploy/docker-compose.prod.yml logs --tail=80 app worker" >&2
exit 1
