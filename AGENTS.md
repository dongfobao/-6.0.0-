# AGENTS.md

## Project summary

YLDQ local data analysis system. Python 3 backend (`dashboard_server.py`) + vanilla HTML/CSS/JS frontend (`web/`). Reads device CSV logs from a `实时数据/` directory and generates an interactive dashboard or a static customer report.

## Two operating modes

| Mode | Entrypoint | Output |
|------|-----------|--------|
| Dev / interactive dashboard | `启动分析系统.bat` | Live HTTP server at `127.0.0.1:8765` |
| Customer delivery | `python customer_delivery_entry.py` | Static `output/分析报告.html` + `.txt` + `.json` |

## Key commands

```bat
:: Start dev server + open browser
启动分析系统.bat

:: Generate customer report (dev machine)
生成客户版报告.bat

:: Package standalone EXE with PyInstaller
打包客户交付版EXE.bat
```

Run tests: `python -m unittest tests.test_parameter_recommendation`

No linter or typechecker is configured for this project.

## Architecture

- `dashboard_server.py` — core module: HTTP server, CSV parsing, analysis, config management, static report generation. Also provides `set_runtime_base()` to redirect data/web directories at runtime.
- `customer_delivery_entry.py` — thin CLI wrapper. Calls `dashboard_server.set_runtime_base()` then `load_analysis()` + `write_customer_outputs()`.
- `parameter_recommendation.py` — stateless recommendation engine. Takes config + history dicts, returns parameter suggestions grouped by confidence (high/medium/low).
- `web/` — static frontend. Contains duplicate CSV parsing regex in `app.js` that **must stay in sync** with `dashboard_server.py` regexes.

## Data directory contract

The `实时数据/` directory (gitignored) must contain:
- `config.json`
- `data_0/log_YYYY_MM_DD.csv` (minute-level environment logs)
- `breath_data/breath_YYYY_MM_DD.csv` (second-level breath logs)
- `run/*.csv` (operational run logs)

The Python backend reads these with hardcoded regexes (`ENV_ROW_RE`, `RUN_ROW_RE`). The frontend `app.js` duplicates these regexes for local import. If you change the CSV format or regex in one place, you must change both.

## Dependencies

Zero third-party Python packages at runtime (stdlib only). PyInstaller is only needed for EXE packaging (`customer_delivery.spec`).

## Analysis caching

`load_analysis()` caches results by file signature (path + size + mtime). Pass `force_refresh=True` to bypass. The cache is also invalidated when config is saved via `POST /api/config`.

## EXE packaging

`customer_delivery.spec` bundles `web/` as PyInstaller data. The frozen executable looks for `实时数据/` next to the EXE. When running frozen (`sys.frozen`), `_MEIPASS` is used as the asset base for `web/`.

## Frontend: static vs. live report

`web/app.js` checks `window.__STATIC_REPORT__`. If truthy, it uses `window.__ANALYSIS__` (embedded JSON). Otherwise it fetches `/api/analysis` from the dev server. The static report HTML is assembled by `build_standalone_report_html()` which inlines CSS + JS + payload into a single file.

## Config write behavior

`POST /api/config` validates and merges the incoming partial config against the current `config.json` on disk (not the in-memory analysis). It writes the merged result back to `config.json` and clears the analysis cache. The schema is defined in `CONFIG_SCHEMA` in `dashboard_server.py`.
