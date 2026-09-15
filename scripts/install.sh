#!/usr/bin/env bash
# Interactive installer for Ackiologs on Linux. Asks how you want it deployed
# (systemd native service, or Docker Compose), which database backend, which
# network interface/port to bind, and how much history to retain — then does it.
#
# Usage:
#   ./scripts/install.sh                 # interactive
#   sudo ./scripts/install.sh            # needed for the systemd method
#   curl -fsSL https://raw.githubusercontent.com/Installation-04/ackiologs/main/scripts/install.sh | sudo bash
#
# Non-interactive / scripted use: export the variables read below (INSTALL_METHOD,
# DB_BACKEND, BIND_HOST, PORT, RETENTION_DAYS, ...) and pass --yes to accept them
# without prompting.
set -euo pipefail

REPO="Installation-04/ackiologs"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/main"
API_LATEST_RELEASE="https://api.github.com/repos/${REPO}/releases/latest"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help)
      sed -n '2,13p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
err()  { printf 'error: %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# Reads from the real terminal even when this script itself was piped into
# bash (curl ... | bash), where stdin is the pipe, not the keyboard.
tty_read() {
  local prompt="$1" __var="$2" reply
  if [ -r /dev/tty ]; then
    read -rp "$prompt" reply < /dev/tty
  else
    read -rp "$prompt" reply
  fi
  printf -v "$__var" '%s' "$reply"
}

ask() {
  # ask "Prompt text" VAR_NAME "default"  -- VAR_NAME may already be set (env
  # override); under --yes that value (or the default) is used with no prompt.
  local prompt="$1" var="$2" default="$3" reply
  local current="${!var:-}"
  [ -n "$current" ] && default="$current"
  if [ "$ASSUME_YES" = "1" ]; then
    printf -v "$var" '%s' "$default"
    return
  fi
  tty_read "$prompt [$default]: " reply
  printf -v "$var" '%s' "${reply:-$default}"
}

ask_secret() {
  local prompt="$1" var="$2" reply
  if [ "$ASSUME_YES" = "1" ]; then
    printf -v "$var" '%s' "${!var:-}"
    return
  fi
  if [ -r /dev/tty ]; then
    read -rsp "$prompt: " reply < /dev/tty
  else
    read -rsp "$prompt: " reply
  fi
  echo
  printf -v "$var" '%s' "$reply"
}

ask_menu() {
  # ask_menu VAR_NAME "Prompt" default_value "value1:Label one" "value2:Label two" ...
  # VAR_NAME may already hold one of the values (env override); under --yes,
  # that value (or default_value) is used directly with no prompt.
  local var="$1" prompt="$2" default_value="$3"
  shift 3
  local pairs=("$@") current="${!var:-}"

  if [ "$ASSUME_YES" = "1" ]; then
    printf -v "$var" '%s' "${current:-$default_value}"
    return
  fi

  echo "$prompt"
  local i values=() default_num=1 pair value label
  for i in "${!pairs[@]}"; do
    pair="${pairs[$i]}"
    value="${pair%%:*}"
    label="${pair#*:}"
    values+=("$value")
    printf '  %d) %s\n' "$((i + 1))" "$label"
    [ "$value" = "${current:-$default_value}" ] && default_num=$((i + 1))
  done
  local choice
  tty_read "Choice [$default_num]: " choice
  choice="${choice:-$default_num}"
  [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#values[@]}" ] \
    || die "invalid choice: $choice"
  printf -v "$var" '%s' "${values[$((choice - 1))]}"
}

random_hex() {
  openssl rand -hex 32 2>/dev/null || python3 -c "import secrets;print(secrets.token_hex(32))"
}

download() { # download <url> <dest>
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$1" -O "$2"
  else
    die "need curl or wget to download $1"
  fi
}

fetch() { # fetch <url> -> stdout
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    die "need curl or wget to fetch $1"
  fi
}

# ---------------------------------------------------------------------------
# 1. gather answers
# ---------------------------------------------------------------------------
bold "Ackiologs installer"
echo

ask_menu INSTALL_METHOD "How do you want to run it?" systemd \
  "systemd:systemd — native service, runs the Linux binary directly" \
  "docker:docker  — Docker Compose deployment"
echo

ask_menu DB_BACKEND "Which database backend?" sqlite \
  "sqlite:sqlite      — zero-config, good for a single site / small-to-medium tag count" \
  "timescaledb:timescaledb — Postgres/TimescaleDB, for production scale and long retention"
echo

if [ "$DB_BACKEND" = "timescaledb" ]; then
  if [ "$INSTALL_METHOD" = "docker" ]; then
    ask_menu TSDB_MODE "TimescaleDB: run it as a container alongside Ackiologs, or connect to one you already have?" managed \
      "managed:managed  — docker-compose.timescale.yml starts TimescaleDB for you" \
      "external:external — provide a connection string to an existing instance"
    if [ "$TSDB_MODE" = "managed" ]; then
      ask_secret "Password for the managed TimescaleDB (blank = random)" POSTGRES_PASSWORD
      [ -z "${POSTGRES_PASSWORD:-}" ] && POSTGRES_PASSWORD="$(random_hex | cut -c1-24)"
    else
      ask "Postgres connection string (postgresql+asyncpg://user:pass@host:5432/db)" \
        DATABASE_URL "postgresql+asyncpg://ackiologs:ackiologs@localhost:5432/ackiologs"
    fi
  else
    TSDB_MODE=external
    ask "Postgres connection string (postgresql+asyncpg://user:pass@host:5432/db)" \
      DATABASE_URL "postgresql+asyncpg://ackiologs:ackiologs@localhost:5432/ackiologs"
  fi
fi
echo

ask_menu BIND_MODE "Which network interface should it listen on?" all \
  "all:all interfaces (0.0.0.0) — reachable from other machines" \
  "local:localhost only (127.0.0.1) — this machine only" \
  "custom:custom address"
case "$BIND_MODE" in
  all) : "${BIND_HOST:=0.0.0.0}" ;;
  local) : "${BIND_HOST:=127.0.0.1}" ;;
  custom) ask "Bind address" BIND_HOST "0.0.0.0" ;;
esac
ask "Port" PORT "8000"
echo

ask "How many days of history to keep (0 = forever)" RETENTION_DAYS "0"
echo

SECRET_KEY="${SECRET_KEY:-$(random_hex)}"

bold "Summary"
info "Install method:    $INSTALL_METHOD"
info "Database:          $DB_BACKEND${TSDB_MODE:+ ($TSDB_MODE)}"
info "Listening on:       ${BIND_HOST}:${PORT}"
info "Retention:          ${RETENTION_DAYS} day(s) (0 = forever)"
echo
if [ "$ASSUME_YES" != "1" ]; then
  tty_read "Proceed? [Y/n]: " CONFIRM
  case "${CONFIRM:-Y}" in [Yy]*|"") ;; *) die "aborted" ;; esac
fi
echo

# ---------------------------------------------------------------------------
# 2. install
# ---------------------------------------------------------------------------
install_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker isn't installed — see https://docs.docker.com/engine/install/"
  docker compose version >/dev/null 2>&1 || die "the 'docker compose' plugin isn't installed"

  local dir="$REPO_ROOT"
  if [ ! -f "$dir/docker-compose.yml" ]; then
    # Not running from a checkout (e.g. this script was curl'd standalone) — the
    # Docker build needs the full source tree, so get it the same way: git clone.
    command -v git >/dev/null 2>&1 || die "git is required to fetch the source for a Docker build — install git, or clone ${REPO} yourself first"
    dir="$(pwd)/ackiologs"
    if [ -d "$dir/.git" ]; then
      bold "Using existing checkout at $dir"
    else
      bold "Cloning ${REPO} into $dir ..."
      git clone --depth 1 "https://github.com/${REPO}.git" "$dir"
    fi
  fi

  cat > "$dir/.env" <<EOF
ACKIOLOGS_SECRET_KEY=${SECRET_KEY}
ACKIOLOGS_AUTH_ENABLED=true
ACKIOLOGS_RETENTION_DAYS=${RETENTION_DAYS}
ACKIOLOGS_HOST_BIND=${BIND_HOST}
ACKIOLOGS_PORT=${PORT}
EOF

  local compose_files=(-f "$dir/docker-compose.yml")
  if [ "$DB_BACKEND" = "timescaledb" ]; then
    if [ "$TSDB_MODE" = "managed" ]; then
      compose_files+=(-f "$dir/docker-compose.timescale.yml")
      echo "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" >> "$dir/.env"
    else
      echo "ACKIOLOGS_DATABASE_URL=${DATABASE_URL}" >> "$dir/.env"
    fi
  fi

  bold "Starting Ackiologs with Docker Compose ..."
  (cd "$dir" && docker compose "${compose_files[@]}" up -d --build)

  echo
  bold "Done. Ackiologs is starting at http://${BIND_HOST}:${PORT}"
  info "First-run admin password: docker compose -f \"$dir/docker-compose.yml\" logs historian | grep 'Created default admin'"
}

install_systemd() {
  [ "$(id -u)" = "0" ] || die "the systemd install needs root — re-run with sudo"

  local install_dir=/opt/ackiologs
  local bin_dir="$install_dir/bin"
  local config_dir=/etc/ackiologs
  local data_dir=/var/lib/ackiologs
  local env_file="$config_dir/ackiologs.env"
  local service_file=/etc/systemd/system/ackiologs.service

  mkdir -p "$bin_dir" "$config_dir" "$data_dir"

  if [ -x "$SCRIPT_DIR/../ackiologs" ]; then
    cp "$SCRIPT_DIR/../ackiologs" "$bin_dir/ackiologs"
  elif [ -x "$SCRIPT_DIR/ackiologs" ]; then
    cp "$SCRIPT_DIR/ackiologs" "$bin_dir/ackiologs"
  else
    bold "Downloading the latest Linux release ..."
    local tmp; tmp="$(mktemp -d)"
    local asset_url
    asset_url="$(fetch "$API_LATEST_RELEASE" | grep -o 'https://[^"]*linux-x86_64[^"]*\.tar\.gz' | head -n1)"
    [ -n "$asset_url" ] || die "couldn't find a Linux release asset — check https://github.com/${REPO}/releases"
    download "$asset_url" "$tmp/ackiologs.tar.gz"
    tar xzf "$tmp/ackiologs.tar.gz" -C "$tmp"
    local extracted; extracted="$(find "$tmp" -maxdepth 1 -type d -name 'ackiologs-linux-*' | head -n1)"
    cp "$extracted/ackiologs" "$bin_dir/ackiologs"
    [ -f "$config_dir/tags.yaml" ] || cp "$extracted/config/tags.yaml" "$config_dir/tags.yaml"
    [ -f "$config_dir/connections.yaml" ] || cp "$extracted/config/connections.yaml" "$config_dir/connections.yaml"
    rm -rf "$tmp"
  fi
  chmod +x "$bin_dir/ackiologs"

  if [ ! -f "$config_dir/tags.yaml" ]; then
    download "$RAW_BASE/config/tags.yaml" "$config_dir/tags.yaml" || true
  fi
  if [ ! -f "$config_dir/connections.yaml" ]; then
    download "$RAW_BASE/config/connections.yaml" "$config_dir/connections.yaml" || true
  fi

  id ackiologs >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin ackiologs
  chown -R ackiologs:ackiologs "$install_dir" "$data_dir" "$config_dir"

  {
    echo "ACKIOLOGS_SECRET_KEY=${SECRET_KEY}"
    echo "ACKIOLOGS_AUTH_ENABLED=true"
    echo "ACKIOLOGS_RETENTION_DAYS=${RETENTION_DAYS}"
    echo "ACKIOLOGS_TAGS_CONFIG_PATH=${config_dir}/tags.yaml"
    echo "ACKIOLOGS_CONNECTIONS_CONFIG_PATH=${config_dir}/connections.yaml"
    if [ "$DB_BACKEND" = "timescaledb" ]; then
      echo "ACKIOLOGS_DATABASE_URL=${DATABASE_URL}"
    else
      echo "ACKIOLOGS_DATABASE_URL=sqlite+aiosqlite:///${data_dir}/ackiologs.db"
    fi
  } > "$env_file"
  chmod 600 "$env_file"
  chown ackiologs:ackiologs "$env_file"

  cat > "$service_file" <<EOF
[Unit]
Description=Ackiologs Industrial Historian
After=network.target

[Service]
Type=simple
User=ackiologs
Group=ackiologs
EnvironmentFile=${env_file}
ExecStart=${bin_dir}/ackiologs --host ${BIND_HOST} --port ${PORT}
WorkingDirectory=${install_dir}
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${data_dir} ${config_dir}
ProtectHome=yes

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now ackiologs

  echo
  bold "Done. Ackiologs is starting at http://${BIND_HOST}:${PORT}"
  info "Logs (and the first-run admin password): journalctl -u ackiologs -f"
  info "Config: $config_dir   Data: $data_dir"
}

if [ "$INSTALL_METHOD" = "docker" ]; then
  install_docker
else
  install_systemd
fi
