"""stock_mcp_server.py  v2.0

J-Quants stock analysis MCP server for personal investment dashboard.

大型リファクタ (Phase C): 実体は mcp_server/ パッケージに分割中。
本ファイルは現状以下を担う:
- mcp_server._context の import（FastMCP インスタンス取得）
- 未移設の helper / tool 群（段階的に mcp_server/*.py へ移行予定）
- MCP サーバー起動: mcp.run()
"""
from __future__ import annotations

import sqlite3
import subprocess
import os
import time
import json
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timedelta

import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── mcp_server パッケージから共通 context を import ──
from mcp_server._context import (
    mcp,
    yf, _YF_AVAILABLE,
    BASE_DIR, DB_PATH, CSV_DIR, CONFIG,
    PROGRESS_FILE, RESULTS_FILE, MASTER_CACHE, PORTFOLIO_FILE, WATCHLIST_FILE,
    GITHUB_DIR, CHART_DIR,
    MASTER_CACHE_TTL_DAYS, BATCH_SIZE, BATCH_SLEEP_SEC, REQUEST_SLEEP_SEC,
    MAX_RETRIES, RETRY_SLEEP_SEC, PARALLEL_WORKERS,
    NIKKEI225_CODE, ETF_CODE_PREFIXES, MAJOR_STOCKS,
    _job_lock, _job_state,
)

# ── private helpers: 後方互換のため re-import (lazy import target) ──
from mcp_server._api import _get_api_key, _headers
from mcp_server._db import (
    _init_db, _save_weekly, _load_weekly, _save_daily_db, _load_daily_db,
)
from mcp_server._fetch import (
    _fetch_daily_yf, _fetch_daily, _daily_to_weekly, _daily_to_df,
)
from mcp_server.minervini import _minervini, _calc_rs
from mcp_server._fins_fetch import _fetch_fins, _fetch_fins_history
from mcp_server.equity import _is_etf, fetch_equity_master, _lookup_name




# ---------------------------------------------------------------------------

# mcp_server パッケージからのツール登録（@mcp.tool デコレータ発火用 import）
# ---------------------------------------------------------------------------
import mcp_server.patterns    # noqa: F401, E402
import mcp_server.fins_tools  # noqa: F401, E402
import mcp_server.portfolio   # noqa: F401, E402
import mcp_server.watchlist   # noqa: F401, E402
import mcp_server.charts      # noqa: F401, E402
import mcp_server.exports     # noqa: F401, E402
import mcp_server.utils       # noqa: F401, E402
import mcp_server.equity      # noqa: F401, E402
import mcp_server.bulk        # noqa: F401, E402
import mcp_server.screening   # noqa: F401, E402
import mcp_server.earnings    # noqa: F401, E402


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
