"""Validate required values without printing credentials."""
import sys
from pathlib import Path
from urllib.parse import urlparse


def read_env(path):
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def check(values):
    failures = []
    if not values.get("DASHSCOPE_API_KEY") or values["DASHSCOPE_API_KEY"] == "<redacted>":
        failures.append("DASHSCOPE_API_KEY is missing")
    base = values.get("PUBLIC_BASE_URL", "")
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname not in ("shynarbuy.com", "www.shynarbuy.com") or base.endswith("/") or parsed.path:
        failures.append("PUBLIC_BASE_URL must use the expected HTTPS domain without path/trailing slash")
    if values.get("MOCK_AI") == "1":
        failures.append("MOCK_AI must not be enabled")
    if values.get("KEEP_AUDIO") == "1":
        failures.append("KEEP_AUDIO must not be enabled for initial production")
    if len(values.get("REGISTRATION_CODE", "")) < 12:
        failures.append("REGISTRATION_CODE needs at least 12 characters")
    return failures


if __name__ == "__main__":
    issues = check(read_env(sys.argv[1]))
    if issues:
        print("Configuration invalid: " + "; ".join(issues))
        raise SystemExit(1)
    print("Private configuration valid; values not displayed.")
