#!/bin/sh
set -eu
# Run only after uploading this exact release to /root/classnotes-staging/release.
umask 077
staging=/root/classnotes-staging/release
test -f "$staging/backend/app.py"
test -f "$staging/deployment/classnotes.service"
test -f /root/classnotes-staging/runtime.env
command -v ffmpeg >/dev/null
if ! id classnotes >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/classnotes --shell /usr/sbin/nologin classnotes
fi
install -d -m 755 /opt/classnotes /opt/classnotes/releases
install -d -m 700 -o classnotes -g classnotes /var/lib/classnotes
release=/opt/classnotes/releases/$(date +%Y%m%d-%H%M%S)
install -d -m 755 "$release"
cp -a "$staging/." "$release/"
# Ensure the app code stays readable while secrets and data stay private.
chmod -R a+rX "$release"
test ! -e "$release/data"
ln -s /var/lib/classnotes "$release/data"
python3 -m venv "$release/.venv"
"$release/.venv/bin/pip" install --disable-pip-version-check -r "$release/requirements.txt"
chmod -R a+rX "$release/.venv"
install -m 600 -o root -g root /root/classnotes-staging/runtime.env /etc/classnotes.env
"$release/.venv/bin/python" "$release/deployment/check_environment.py" /etc/classnotes.env
test ! -e /opt/classnotes/current
ln -s "$release" /opt/classnotes/current
install -m 644 "$release/deployment/classnotes.service" /etc/systemd/system/classnotes.service
systemctl daemon-reload
systemctl enable --now classnotes
sleep 2
systemctl is-active classnotes
curl --fail --silent http://127.0.0.1:8000/api/config
printf '\nRELEASE_READY=%s\n' "$release"
# Do not switch nginx here: first verify the real AI flow and preserve rollback.
