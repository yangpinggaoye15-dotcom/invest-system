#!/usr/bin/env python3
"""run_teams.py を .env 読み込み付きで直接実行"""
import os, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

# 環境変数のデフォルト設定
if not os.environ.get("INVEST_BASE_DIR"):
    os.environ["INVEST_BASE_DIR"] = BASE
if not os.environ.get("INVEST_DATA_DIR"):
    os.environ["INVEST_DATA_DIR"] = r"C:\Users\yohei\Documents\invest-data"
if not os.environ.get("INVEST_GITHUB_DIR"):
    os.environ["INVEST_GITHUB_DIR"] = BASE

# .env 読み込み
env_path = os.path.join(BASE, ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    print(".env loaded")

for k in ["ANTHROPIC_API_KEY", "GEMINI_API", "JQUANTS_API_KEY"]:
    v = os.environ.get(k, "")
    status = "OK (" + v[:8] + "...)" if v and not v.startswith("your_") else "NG"
    print(f"  {k}: {status}")

print("\n=== run_teams.py 開始 ===\n")
sys.stdout.flush()

# run_teams を exec で直接実行
teams_path = os.path.join(BASE, "run_teams.py")
with open(teams_path, encoding="utf-8") as f:
    code = f.read()

exec(compile(code, teams_path, "exec"), {"__name__": "__main__", "__file__": teams_path})
