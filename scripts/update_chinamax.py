#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from pathlib import Path
import math
import sys
from typing import List, Optional, Tuple
import urllib.request


SOURCE_URL = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/ChinaMax/ChinaMax.list"
RAW_BASE_URL = "https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/ChinaMax"
CHUNK_SIZE = 100_000

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "ChinaMax"

SUPPORTED_TYPES = {
    "DOMAIN": "2",
    "DOMAIN-SUFFIX": "2",
    "DOMAIN-KEYWORD": "3",
    "IP-CIDR": "0",
    "IP-CIDR6": "1",
}

TRACKED_UNSUPPORTED_TYPES = {"PROCESS-NAME", "IP-ASN"}


def fetch_source() -> str:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "mihomo_override-chinamax-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def normalize_rule_line(raw_line: str) -> Optional[Tuple[str, str]]:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("- "):
        line = line[2:].strip()

    line = line.strip("'\"")
    if not line or line.endswith(":") or line.lower() == "payload":
        return None

    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 2:
        return None

    return parts[0].upper(), parts[1].strip("'\"")


def convert(source: str) -> Tuple[List[str], Counter, Counter]:
    rules: List[str] = []
    converted: Counter[str] = Counter()
    skipped: Counter[str] = Counter()

    for raw_line in source.splitlines():
        normalized = normalize_rule_line(raw_line)
        if normalized is None:
            continue

        rule_type, value = normalized
        if not value:
            skipped["Other"] += 1
            continue

        mapped_type = SUPPORTED_TYPES.get(rule_type)
        if mapped_type is not None:
            rules.append(f"{mapped_type}, {value}")
            converted[rule_type] += 1
        elif rule_type in TRACKED_UNSUPPORTED_TYPES:
            skipped[rule_type] += 1
        else:
            skipped["Other"] += 1

    if not rules:
        raise RuntimeError("No supported ChinaMax rules were converted.")

    return rules, converted, skipped


def write_chunks(rules: List[str]) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for old_chunk in OUTPUT_DIR.glob("ChinaMax-*.arrs"):
        old_chunk.unlink()

    chunk_count = math.ceil(len(rules) / CHUNK_SIZE)
    for index in range(chunk_count):
        chunk = rules[index * CHUNK_SIZE : (index + 1) * CHUNK_SIZE]
        output_path = OUTPUT_DIR / f"ChinaMax-{index + 1:03d}.arrs"
        header = [
            f"name = ChinaMax {index + 1:03d}",
            "",
            f"# Source: {SOURCE_URL}",
            "# Upstream format: Clash classical list",
            "# Note: DOMAIN entries are mapped to Domain Suffix because Anywhere has no exact-domain rule type.",
            "# Note: PROCESS-NAME and IP-ASN entries are unsupported by Anywhere routing and are skipped.",
            f"# Chunk: {index + 1}/{chunk_count}",
            f"# Rules: {len(chunk)}",
            "",
        ]
        output_path.write_text("\n".join(header + chunk) + "\n", encoding="utf-8")

    return chunk_count


def write_readme(rule_count: int, chunk_count: int, converted: Counter[str], skipped: Counter[str]) -> None:
    subscription_lines = "\n".join(
        f"- {RAW_BASE_URL}/ChinaMax-{index + 1:03d}.arrs"
        for index in range(chunk_count)
    )

    content = f"""# ChinaMax 规则转换

来源：{SOURCE_URL}

说明：`ChinaMax.yaml` 只包含较小的 payload 子集，这里使用 `ChinaMax.list` 完整列表转换。

推荐订阅地址（需要全部导入）：

{subscription_lines}

已转换规则数：{rule_count}

分片数量：{chunk_count}

单个分片规则上限：{CHUNK_SIZE}

转换规则：

- `DOMAIN` -> `2, value`：{converted["DOMAIN"]} 条。Anywhere 当前没有精确域名类型，所以映射为域名后缀，匹配范围会略宽。
- `DOMAIN-SUFFIX` -> `2, value`：{converted["DOMAIN-SUFFIX"]} 条。
- `DOMAIN-KEYWORD` -> `3, value`：{converted["DOMAIN-KEYWORD"]} 条。
- `IP-CIDR` -> `0, value`：{converted["IP-CIDR"]} 条。
- `IP-CIDR6` -> `1, value`：{converted["IP-CIDR6"]} 条。
- 跳过 `PROCESS-NAME`：{skipped["PROCESS-NAME"]} 条。
- 跳过 `IP-ASN`：{skipped["IP-ASN"]} 条。
- 跳过其他不支持规则：{skipped["Other"]} 条。

使用方式：在 Anywhere 的 Routing Rules 里导入上面的全部 `ChinaMax-*.arrs`，然后把每个规则集的 `Route To` 设置为 `DIRECT`。

自动更新：仓库中的 GitHub Actions 会每天运行一次 `scripts/update_chinamax.py`，拉取上游 `ChinaMax.list` 重新转换；如果结果有变化，会自动提交到 `main`。
"""
    (OUTPUT_DIR / "README.md").write_text(content, encoding="utf-8")


def main() -> int:
    source = fetch_source()
    rules, converted, skipped = convert(source)
    chunk_count = write_chunks(rules)
    write_readme(len(rules), chunk_count, converted, skipped)
    print(f"Converted {len(rules)} ChinaMax rules into {chunk_count} chunks.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"update_chinamax.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
