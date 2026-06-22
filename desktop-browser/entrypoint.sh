#!/usr/bin/env bash
set -euo pipefail

profile_dir="${DESKTOP_BROWSER_PROFILE_DIR:-/data/profile}"
mkdir -p "${profile_dir}"
chown -R browser:browser "${profile_dir}"
rm -f "${profile_dir}/SingletonLock" "${profile_dir}/SingletonSocket" "${profile_dir}/SingletonCookie"
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

Xvfb "${DISPLAY}" -screen 0 1440x900x24 -ac +extension RANDR &
xvfb_pid=$!

for _ in $(seq 1 50); do
  if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

openbox &
openbox_pid=$!
x11vnc -display "${DISPLAY}" -forever -shared -nopw -rfbport 5900 -localhost &
vnc_pid=$!
websockify --web=/usr/share/novnc 6080 localhost:5900 &
novnc_pid=$!
python3 /usr/local/bin/desktop-browser-tcp-proxy &
proxy_pid=$!

runuser -u browser -- env DISPLAY="${DISPLAY}" chromium \
  --no-sandbox \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9223 \
  --user-data-dir="${profile_dir}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --start-maximized \
  --window-size=1440,900 \
  about:blank &
chromium_pid=$!

cleanup() {
  kill "${chromium_pid}" "${proxy_pid}" "${novnc_pid}" "${vnc_pid}" "${openbox_pid}" "${xvfb_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait -n "${chromium_pid}" "${proxy_pid}" "${novnc_pid}" "${vnc_pid}" "${openbox_pid}" "${xvfb_pid}"
