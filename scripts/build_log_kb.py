import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


CATEGORY_RULES = [
    ("flowTransducer", "sensor.flow"),
    ("breathRecord", "sensor.breath"),
    ("I2CHumidity", "sensor.humidity.i2c"),
    ("Humidity.c", "sensor.humidity.modbus"),
    ("pressure", "sensor.pressure"),
    ("config", "config.parse"),
    ("freertos.c", "system.startup"),
    ("main.c", "system.startup"),
    ("Watchdog.c", "system.startup"),
    ("LinkerDriver", "comm.linker"),
    ("lora", "comm.lora"),
    ("lte4g", "comm.lte4g"),
    ("wapi", "comm.wapi"),
    ("IEC61850", "comm.iec61850"),
    ("IEC104", "comm.iec104"),
    ("Storage", "storage.sd"),
    ("OnlinePower", "control.power"),
    ("hotCtrl", "control.heat"),
]

LEVEL_RULES = {
    "log_e": ("error", "E"),
    "log_w": ("warning", "W"),
    "log_i": ("info", "I"),
    "printf": ("info", "I"),
}

PRINTF_PATTERNS = [
    (r"%0?\d*[lL]?[dDuU]", r"(\\d+)"),
    (r"%0?\d*[xX]", r"([0-9A-Fa-f]+)"),
    (r"%0?\d*(?:\.\d+)?f", r"([+-]?(?:\\d+(?:\\.\\d+)?|\\.\\d+))"),
    (r"%s", r"(.+?)"),
    (r"%c", r"(.)"),
]


@dataclass
class EntrySeed:
    source_file: str
    line_number: str
    level_token: str
    message: str


def slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "log_entry"


def infer_category(source_file: str) -> str:
    lowered = source_file.lower()
    for needle, category in CATEGORY_RULES:
        if needle.lower() in lowered:
            return category
    return "app.error"


def infer_level(level_token: str, message: str) -> tuple[str, str]:
    severity, level = LEVEL_RULES.get(level_token, ("info", "I"))
    message_upper = message.upper()
    if "FATAL" in message_upper:
        return "fatal", "E"
    if "ALARM" in message_upper or "FAILED" in message_upper:
        return ("critical" if severity != "warning" else "warning"), level
    return severity, level


def convert_printf_to_regex(message: str) -> str:
    escaped = re.escape(message)
    for spec, replacement in PRINTF_PATTERNS:
        escaped = re.sub(re.escape(spec), replacement, escaped)
    return f"^{escaped}$"


def build_match(message: str) -> dict:
    if "%" in message:
        return {"type": "regex", "patterns": [convert_printf_to_regex(message)]}
    return {"type": "exact", "patterns": [message]}


def parse_markdown(md_path: Path) -> list[EntrySeed]:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    current_file = ""
    entries: list[EntrySeed] = []
    row_re = re.compile(r'^\|\s*([^|]+?)\s*\|\s*`?([^|`]+)`?\s*\|\s*(.+?)\s*\|$')

    for line in lines:
        if line.startswith("### "):
            current_file = line[4:].strip()
            continue
        match = row_re.match(line)
        if not match:
            continue
        line_number, level_token, message = match.groups()
        if line_number in {"行号", "琛屽彿"}:
            continue
        message = message.strip()
        if message.startswith('"') and message.endswith('"'):
            message = message[1:-1]
        entries.append(EntrySeed(current_file, line_number, level_token.strip(), message))
    return entries


def build_entry(seed: EntrySeed) -> dict:
    category = infer_category(seed.source_file)
    severity, level = infer_level(seed.level_token, seed.message)
    entry_id = slugify(f"{Path(seed.source_file).stem}_{seed.message[:48]}")
    return {
        "id": entry_id,
        "match": build_match(seed.message),
        "scope": {
            "files": [seed.source_file] if seed.source_file else [],
            "levels": [level],
        },
        "output": {
            "category": category,
            "severity": severity,
            "tags": [],
            "zh_title": seed.message,
            "zh_message": seed.message,
            "explanation": "",
            "suggestion": "",
            "impact": "",
        },
        "_seed": {
            "line_number": seed.line_number,
            "level_token": seed.level_token,
        },
    }


def build_document(entries: list[dict]) -> dict:
    return {
        "meta": {
            "version": "generated-skeleton",
            "generated_from": "错误和警告信息汇总.md",
            "total_entries": len(entries),
        },
        "categories": {},
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build log knowledge base skeleton from 错误和警告信息汇总.md")
    parser.add_argument("input", type=Path, help="Path to 错误和警告信息汇总.md")
    parser.add_argument("output", type=Path, help="Output JSON path")
    args = parser.parse_args()

    seeds = parse_markdown(args.input)
    entries = [build_entry(seed) for seed in seeds]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_document(entries), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(entries)} knowledge-base skeleton entries -> {args.output}")


if __name__ == "__main__":
    main()
