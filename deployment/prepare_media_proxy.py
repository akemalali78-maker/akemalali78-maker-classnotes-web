#!/usr/bin/env python3
"""Expose only temporary /media/ to ASR; keep the old homepage on port 4173.

Server use: python3 deployment/prepare_media_proxy.py --apply
Local validation: python3 deployment/prepare_media_proxy.py --self-test
This deliberately preserves the guards in switch_nginx.py for full cutover.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid


SITE_LINK = Path("/etc/nginx/sites-enabled/shynarbuy")
BACKUP_DIRECTORY = Path("/root/site-backups/shynarbuy-20261013-200644")
OLD_UPSTREAM = "proxy_pass http://127.0.0.1:4173;"
MARKER = "# CODEX_CLASSNOTES_TEMP_MEDIA_PROXY"


class Refused(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def structural_code(text):
    """Mask comments/quotes without shifting character positions or newlines."""
    result = list(text)
    quote = None
    comment = False
    escaped = False
    for i, char in enumerate(text):
        if comment:
            if char == "\n":
                comment = False
            else:
                result[i] = " "
        elif quote:
            if char != "\n":
                result[i] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "#":
            comment = True
            result[i] = " "
        elif char in {"'", '"'}:
            quote = char
            result[i] = " "
    require(quote is None, "unterminated_nginx_quote")
    return "".join(result)


def scopes(code):
    stack = []
    completed = []
    last_delimiter = -1
    for i, char in enumerate(code):
        if char == "{":
            block = {"start": last_delimiter + 1, "open": i,
                     "header": code[last_delimiter + 1:i].strip(),
                     "parent": stack[-1] if stack else None}
            stack.append(block)
            last_delimiter = i
        elif char == "}":
            require(bool(stack), "unexpected_nginx_closing_brace")
            block = stack.pop()
            block["close"] = i
            completed.append(block)
            last_delimiter = i
        elif char == ";":
            last_delimiter = i
    require(not stack, "unclosed_nginx_scope")
    return completed


def build_candidate(text):
    require(MARKER not in text, "media_proxy_already_prepared_inspect_before_retry")
    code = structural_code(text)
    require(code.count(OLD_UPSTREAM) == 1 and text.count(OLD_UPSTREAM) == 1,
            "expected_exactly_one_old_4173_upstream")
    require(len(re.findall(r"client_max_body_size\s+10[Mm];", code)) == 1,
            "expected_exactly_one_10M_limit_for_later_switch")
    require(not re.search(r"\blocation\b[^;{}]*/media(?:/|\b)", code),
            "existing_media_location_requires_manual_review")
    blocks = scopes(code)
    require(not any(block["header"].startswith("location")
                    and re.search(r"\blocation\s+[^\n{]*['\"]", text[block["start"]:block["open"]])
                    for block in blocks), "quoted_location_selector_requires_manual_review")
    upstream_index = code.index(OLD_UPSTREAM)
    roots = [block for block in blocks
             if re.fullmatch(r"location\s+/", block["header"])
             and block["open"] < upstream_index < block["close"]]
    require(len(roots) == 1, "old_upstream_not_in_unique_root_location")
    root = roots[0]
    server = root["parent"]
    require(server is not None and server["header"] == "server", "root_not_direct_server_child")
    server_code = code[server["open"] + 1:server["close"]]
    names = re.findall(r"\bserver_name\s+([^;]+);", server_code)
    allowed_names = ["shynarbuy.com", "www.shynarbuy.com"]
    require(len(names) == 1 and names[0].split() in
            (allowed_names, allowed_names + ["43.128.20.59"]),
            "expected_shynarbuy_server_names")
    require(re.search(r"\blisten\s+[^;]*\b443\b[^;]*\bssl\b[^;]*;", server_code),
            "old_upstream_not_in_https_server")
    location_index = code.index("location", root["start"], root["open"])
    line_start = text.rfind("\n", 0, location_index) + 1
    indentation = text[line_start:location_index]
    require(not indentation.strip(), "root_location_not_on_own_line")
    indent = indentation
    inner = indent + "    "
    media = "\n".join([
        indent + MARKER,
        indent + "location ^~ /media/ {",
        inner + "proxy_pass http://127.0.0.1:8000;",
        inner + "proxy_http_version 1.1;",
        inner + "proxy_set_header Host $host;",
        inner + "proxy_set_header X-Real-IP $remote_addr;",
        inner + "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        inner + "proxy_set_header X-Forwarded-Proto $scheme;",
        inner + "proxy_connect_timeout 10s;",
        inner + "proxy_read_timeout 330s;",
        inner + "proxy_buffering off;",
        inner + "proxy_cache off;",
        inner + "access_log off;",
        inner + 'add_header Cache-Control "no-store" always;',
        inner + "limit_except GET { deny all; }",
        indent + "}",
        "",
        "",
    ])
    candidate = text[:line_start] + media + text[line_start:]
    require(candidate.count(OLD_UPSTREAM) == 1, "candidate_changed_old_homepage_upstream")
    require(len(re.findall(r"client_max_body_size\s+10[Mm];", candidate)) == 1,
            "candidate_changed_future_switch_limit")
    return candidate


def command_ok(command):
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=45, check=False).returncode == 0


def replace_bytes(target, contents, metadata):
    """Replace resolved regular file atomically, preserving owner and mode."""
    descriptor, temporary = tempfile.mkstemp(prefix=".classnotes-media-", dir=target.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, metadata.st_mode & 0o7777)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def apply():
    require(os.geteuid() == 0, "root_required")
    target = SITE_LINK.resolve(strict=True)
    require(target.is_relative_to(Path("/etc/nginx")) and target.is_file(), "unexpected_nginx_target")
    require(BACKUP_DIRECTORY.is_dir() and not BACKUP_DIRECTORY.is_symlink()
            and BACKUP_DIRECTORY.resolve() == BACKUP_DIRECTORY, "verified_backup_directory_missing")
    original = target.read_bytes()
    candidate = build_candidate(original.decode("utf-8")).encode("utf-8")
    require(command_ok(["nginx", "-t"]), "original_nginx_configuration_invalid")
    metadata = target.stat()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    backup = BACKUP_DIRECTORY / ("nginx-before-media-proxy-" + suffix + ".conf")
    # A unique exclusive backup is never overwritten, even on retry.
    with backup.open("xb") as output:
        output.write(original)
        output.flush()
        os.fsync(output.fileno())
    backup.chmod(0o600)
    require(backup.read_bytes() == original, "backup_verification_failed")
    require(target.read_bytes() == original, "nginx_configuration_changed_concurrently")
    modified = False
    try:
        replace_bytes(target, candidate, metadata)
        modified = True
        require(command_ok(["nginx", "-t"]), "candidate_nginx_test_failed")
        require(command_ok(["systemctl", "reload", "nginx"]), "candidate_nginx_reload_failed")
    except BaseException:
        if modified:
            replace_bytes(target, original, metadata)
            restored = target.read_bytes() == original
            try:
                restored = command_ok(["nginx", "-t"]) and restored
                reloaded = command_ok(["systemctl", "reload", "nginx"])
            except Exception:
                restored, reloaded = False, False
            print(json.dumps({"ok": False, "original_restored": restored,
                              "original_reloaded": reloaded, "backup": str(backup)}))
        raise
    print(json.dumps({"ok": True, "homepage_upstream": "127.0.0.1:4173",
                      "media_upstream": "127.0.0.1:8000", "backup": str(backup)}))


def self_test():
    sample = """server {
    server_name shynarbuy.com www.shynarbuy.com;
    listen 443 ssl;
    client_max_body_size 10M;
    # A commented brace } must not change block parsing.
    location / {
        proxy_pass http://127.0.0.1:4173;
        proxy_set_header Host $host;
    }
}
server {
    listen 80;
    server_name shynarbuy.com www.shynarbuy.com;
    return 301 https://$host$request_uri;
}
"""
    result = build_candidate(sample)
    with_ip = sample.replace("server_name shynarbuy.com www.shynarbuy.com;",
                             "server_name shynarbuy.com www.shynarbuy.com 43.128.20.59;")
    require(build_candidate(with_ip).count(OLD_UPSTREAM) == 1,
            "self_test_verified_ip_server_name_failed")
    require(result.count(OLD_UPSTREAM) == 1 and result.count("proxy_pass http://127.0.0.1:8000;") == 1,
            "self_test_upstreams_failed")
    require(result.replace(result[result.index("    " + MARKER):result.index("    location / {")], "") == sample,
            "self_test_untouched_original_failed")
    # These are the exact future switch_nginx.py replacement contracts.
    require("server_name shynarbuy.com www.shynarbuy.com" in result, "self_test_switch_hostname_failed")
    switched = result.replace(OLD_UPSTREAM, "proxy_pass http://127.0.0.1:8000;")
    _, count = re.subn(r"client_max_body_size\s+10[Mm];", "client_max_body_size 20m;", switched)
    require(count == 1, "self_test_future_switch_failed")
    for unsafe in (result, sample.replace("443 ssl", "8443 ssl"),
                   sample.replace("    location / {", "    location /media/ { deny all; }\n    location / {"),
                   sample.replace("    location / {", '    location "/media/" { deny all; }\n    location / {'),
                   sample.replace("location / {", "location /api/ {"),
                   sample.replace("www.shynarbuy.com;", "www.shynarbuy.com 43.128.20.60;"),
                   sample.replace("www.shynarbuy.com;", "www.shynarbuy.com other.invalid;"),
                   sample.replace("shynarbuy.com www.shynarbuy.com", "unrelated.invalid")):
        try:
            build_candidate(unsafe)
        except Refused:
            pass
        else:
            raise AssertionError("unsafe nginx fixture accepted")
    print("self_test_ok: only media routing added; old homepage and full-switch guards preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    try:
        self_test() if arguments.self_test else apply()
    except Exception as error:
        # Fixed guard messages contain no config bodies, keys or session tokens.
        message = str(error) if isinstance(error, Refused) else type(error).__name__
        raise SystemExit("MEDIA_PROXY_REFUSED_OR_FAILED: " + message) from None
