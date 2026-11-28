#!/usr/bin/env bash
# Adapted from Top10-Movies/scripts/warp_proxy.sh.
# Pinned Cloudflare WARP userspace route; credentials stay in RUNNER_TEMP.
set -euo pipefail
umask 077
PORT="${WARP_SOCKS_PORT:-40000}"
[[ "$PORT" =~ ^[0-9]+$ ]] || exit 1
PORT=$((10#$PORT))
(( PORT >= 1024 && PORT <= 65535 )) || exit 1
DIR="$RUNNER_TEMP/warp"
mkdir -p "$DIR"
cd "$DIR"
curl --fail --silent --show-error --location --retry 2 --max-time 45 \
  https://github.com/ViRb3/wgcf/releases/download/v2.3.1/wgcf_2.3.1_linux_amd64 -o wgcf
curl --fail --silent --show-error --location --retry 2 --max-time 45 \
  https://github.com/windtf/wireproxy/releases/download/v1.1.3/wireproxy_linux_amd64.tar.gz -o wireproxy.tar.gz
printf '%s  %s\n' 4fb7a136aa470ece11d17949c7db07b040ec9c604742dc8680bcf1889f85d0c8 wgcf \
  e88c1d090740373fc606c1bafd81d9a5eadc642cce5667616e20e9d7a444f51c wireproxy.tar.gz |
  sha256sum --check --status
tar -xzf wireproxy.tar.gz
chmod +x wgcf wireproxy
if ! timeout 45 ./wgcf register --accept-tos >register.log 2>&1; then
  echo "::warning title=WARP unavailable::Registration did not complete; direct sources remain available."
  exit 0
fi
if ! timeout 30 ./wgcf generate >generate.log 2>&1; then
  echo "::warning title=WARP unavailable::Profile generation failed."
  exit 0
fi
{
  cat wgcf-profile.conf
  printf '\n[Socks5]\nBindAddress = 127.0.0.1:%s\n' "$PORT"
} >wireproxy.conf
./wireproxy -c wireproxy.conf >wireproxy.log 2>&1 &
echo "$!" >proxy.pid
for _ in $(seq 1 18); do
  if trace="$(curl --silent --max-time 5 --socks5-hostname "127.0.0.1:$PORT" https://www.cloudflare.com/cdn-cgi/trace)" &&
    [[ "$trace" == *"warp=on"* ]]; then
    echo "YTDLP_FALLBACK_PROXY=socks5h://127.0.0.1:$PORT" >>"$GITHUB_ENV"
    echo "::notice title=WARP ready::The history runner has the same fallback route as Top10-Movies."
    exit 0
  fi
  sleep 2
done
echo "::warning title=WARP unavailable::The route did not become ready; direct archive sources remain enabled."
