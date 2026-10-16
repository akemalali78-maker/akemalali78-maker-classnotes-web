"""Switch only the verified old upstream; preserve SSL and make rollback copy."""
from pathlib import Path
import re
import shutil
import subprocess
import sys

config = Path("/etc/nginx/sites-enabled/shynarbuy").resolve(strict=True)
if not config.is_relative_to(Path("/etc/nginx")):
    raise SystemExit("Unexpected nginx config target; refused")
text = config.read_text()
if text.count("proxy_pass http://127.0.0.1:4173;") != 1:
    raise SystemExit("Expected exactly one old upstream; refused")
if "server_name shynarbuy.com www.shynarbuy.com" not in text:
    raise SystemExit("Expected site hostname; refused")
backup = Path("/root/site-backups/shynarbuy-20261013-200644/nginx-before-switch.conf")
if backup.exists():
    raise SystemExit("Rollback copy already exists; inspect before retrying")
shutil.copy2(config, backup)
backup.chmod(0o600)
new = text.replace("proxy_pass http://127.0.0.1:4173;", """proxy_pass http://127.0.0.1:8000;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_read_timeout 1800s;
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Referrer-Policy strict-origin-when-cross-origin always;
        add_header Permissions-Policy 'microphone=(self), camera=(), geolocation=()' always;""")
new, count = re.subn(r"client_max_body_size\s+10[Mm];", "client_max_body_size 20m;", new)
if count != 1:
    raise SystemExit("Expected one 10M upload limit; refused")
config.write_text(new)
try:
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
except subprocess.CalledProcessError:
    shutil.copy2(backup, config)
    subprocess.run(["nginx", "-t"], check=False)
    subprocess.run(["systemctl", "reload", "nginx"], check=False)
    raise SystemExit("Switch failed; old config restored") from None
print("NGINX_SWITCH_OK; old Node service has not been stopped")
