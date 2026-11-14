#!/bin/sh
# Build dist/setup-exchange.sh: installer/setup-head.sh, a line __PAYLOAD_BELOW__, then the app as a base64 tarball.
#   sh installer/build.sh
# Household defaults come from deploy/deploy.env (git-ignored; see deploy/deploy.env.example). Without it nothing
# is baked in. DEPLOY_ENV=<file> reads another file.
# Every top-level *.py ships, found by glob, so a new module needs no edit here. static/ ships when it exists.
set -eu
cd "$(dirname "$0")/.."
ENV_FILE=${DEPLOY_ENV:-deploy/deploy.env}
STAGE=$(mktemp -d /tmp/exchange-stage.XXXXXX 2>/dev/null || mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p dist "$STAGE/exchange"

for f in *.py; do
  [ -f "$f" ] || { echo "No top-level *.py files found."; exit 1; }
  cp "$f" "$STAGE/exchange/"
done
[ -d static ] && cp -r static "$STAGE/exchange/static"
[ -f ops/exchange-backup ] || { echo "ops/exchange-backup is missing."; exit 1; }
mkdir -p "$STAGE/exchange/ops" && cp ops/exchange-backup "$STAGE/exchange/ops/"

# Clean cache directories portably (avoid find -exec + which BusyBox find can reject)
find "$STAGE" \( -name __pycache__ -o -name .pytest_cache \) -exec rm -rf {} \; 2>/dev/null || true

# Household defaults: ': "${KEY:=value}"' lines, so a variable in the environment still wins.
# Only APP_NAME and EXCHANGE_PORT are baked. ADMIN_PASSWORD_HASH holds dollar signs and is a secret: set it on the
# host (README), never in a file that is built into the installer. SECRET_KEY is never set: the app makes its own.
DEFAULTS="$STAGE/defaults"
: > "$DEFAULTS"
if [ -f "$ENV_FILE" ]; then
  for key in APP_NAME EXCHANGE_PORT; do
    val=$(sed -n "s/^$key=//p" "$ENV_FILE" | head -n1 | sed "s/^[\"']//;s/[\"']\$//")
    if printf '%s' "$val" | grep -q '["`$\\]'; then
      echo "$key in $ENV_FILE contains a character that is not allowed: double quote, backtick, dollar sign or backslash."; exit 1
    fi
    # shellcheck disable=SC2016  # the ${...} is meant for the installer, not for this shell
    [ -n "$val" ] && printf ': "${%s:=%s}"\n' "$key" "$val" >> "$DEFAULTS"
  done
else
  echo "note: $ENV_FILE not found; no household defaults are baked in (copy deploy/deploy.env.example)." >&2
fi

# Check for GNU tar options (--owner/--group) which BusyBox tar does not support
TAR_EXTRA=""
if tar --owner=0 --group=0 --help >/dev/null 2>&1; then
  TAR_EXTRA="--owner=0 --group=0"
fi

OUT=dist/setup-exchange.sh
{
  sed "/^# __DEPLOY_DEFAULTS__\$/r $DEFAULTS" installer/setup-head.sh
  echo "__PAYLOAD_BELOW__"
  # shellcheck disable=SC2086  # TAR_EXTRA is empty or two flags: it must word-split
  ( cd "$STAGE" && tar $TAR_EXTRA -czf - exchange ) | base64
} > "$OUT"
chmod +x "$OUT"
sh -n "$OUT"
echo "Built $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"
