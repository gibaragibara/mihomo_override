#!/usr/bin/env python3
"""Convert Loon LPX plugins to Anywhere MITM (.amrs) rule sets."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = Path(__file__).resolve().parent / "surge_loon_shim.js"
USER_AGENT = "script-hub/1.0.0"
MAX_RULES = 10_000


@dataclass
class ConversionResult:
    name: str
    hostnames: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    routing_rules: List[str] = field(default_factory=list)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_metadata(lines: List[str]) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for line in lines:
        if line.startswith("#!"):
            key, _, value = line[2:].partition("=")
            meta[key.strip()] = value.strip()
    return meta


def parse_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") and not line.startswith("#!"):
            if current and line.startswith("#"):
                continue
            if not line:
                continue
        match = re.fullmatch(r"\[([^\]]+)\]", line)
        if match:
            current = match.group(1).lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(raw.rstrip())
    return sections


def parse_arguments(section_lines: List[str]) -> Dict[str, str]:
    args: Dict[str, str] = {}
    for line in section_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, rest = stripped.partition("=")
        name = name.strip()
        rest = rest.strip()
        if not name:
            continue
        if rest.startswith("switch"):
            parts = [part.strip().strip('"') for part in rest.split(",")]
            args[name] = parts[1] if len(parts) > 1 else "false"
        elif rest.startswith("select"):
            parts = [part.strip().strip('"') for part in rest.split(",")]
            args[name] = parts[1] if len(parts) > 1 else ""
        elif rest.startswith("input"):
            parts = [part.strip().strip('"') for part in rest.split(",")]
            args[name] = parts[1] if len(parts) > 1 else ""
        else:
            args[name] = rest
    return args


def split_hostname_list(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"\s*,\s*", value) if item.strip()]


def quote_csv(value: str) -> str:
    if "," in value or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def jq_inline_to_script(jq_expr: str) -> str:
    expr = jq_expr.strip().strip("'\"")
    return textwrap.dedent(
        f"""
        function process(ctx) {{
          var shim = __awSetupSurgeLoonShim(ctx, {{}});
          try {{
            var text = Anywhere.codec.utf8.decode(ctx.body);
            var data = JSON.parse(text);
            var transformed = (function(data) {{
              {expr}
              return data;
            }})(data);
            if (transformed !== undefined) {{
              ctx.body = Anywhere.codec.utf8.encode(JSON.stringify(transformed));
            }}
          }} catch (e) {{
            Anywhere.log.warning("jq-inline: " + e);
          }}
          shim.applyDone();
        }}
        """
    ).strip()


def jq_file_to_script(jq_source: str) -> str:
    # Kelee JQ files are usually `.data.foo = bar` assignments on the parsed object.
    body = jq_source.strip()
    if not body:
        return ""
    return textwrap.dedent(
        f"""
        function process(ctx) {{
          var shim = __awSetupSurgeLoonShim(ctx, {{}});
          try {{
            var text = Anywhere.codec.utf8.decode(ctx.body);
            var data = JSON.parse(text);
            var transformed = (function(data) {{
              {body}
              return data;
            }})(data);
            if (transformed !== undefined) {{
              ctx.body = Anywhere.codec.utf8.encode(JSON.stringify(transformed));
            }}
          }} catch (e) {{
            Anywhere.log.warning("jq-file: " + e);
          }}
          shim.applyDone();
        }}
        """
    ).strip()


def wrap_external_script(script_source: str, argument_defaults: Dict[str, str], is_binary: bool) -> str:
    shim = SHIM_PATH.read_text(encoding="utf-8")
    arg_json = json.dumps(argument_defaults, ensure_ascii=False)
    mode = "binary" if is_binary else "text"
    return (
        shim
        + "\n\n"
        + textwrap.dedent(
            f"""
            async function process(ctx) {{
              var shim = __awSetupSurgeLoonShim(ctx, {arg_json});
              var __mode = "{mode}";
              try {{
                {script_source}
              }} catch (e) {{
                Anywhere.log.warning("plugin-script: " + e);
              }}
              if (!shim.applyDone() && __mode === "text" && ctx.phase === "response") {{
                var current = Anywhere.codec.utf8.decode(ctx.body);
                if ($response && $response.body != null && $response.body !== current) {{
                  ctx.body = Anywhere.codec.utf8.encode($response.body);
                }}
              }}
            }}
            """
        ).strip()
    )


def encode_script_rule(phase: int, pattern: str, script_source: str) -> Optional[str]:
    if not pattern:
        return None
    payload = base64.b64encode(script_source.encode("utf-8")).decode("ascii")
    return f"{phase}, 100, {pattern}, {payload}"


def parse_rewrite_line(
    line: str,
    warnings: List[str],
) -> List[str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return []

    # response-header-add
    header_add = re.match(
        r"^(?P<pattern>\^\S+)\s+response-header-add\s+(?P<name>[^\s]+)\s+(?P<value>.+)$",
        stripped,
    )
    if header_add:
        return [
            "1, 1, "
            f"{header_add.group('pattern')}, "
            f"{header_add.group('name')}, "
            f"{quote_csv(header_add.group('value'))}"
        ]

    redirect = re.match(
        r"^(?P<pattern>\(.+?\))\s+(?P<code>30[27])\s+(?P<target>.+)$",
        stripped,
    )
    if redirect:
        target = redirect.group("target").strip()
        if not target.startswith("http"):
            warnings.append(f"unsupported redirect target: {stripped[:120]}")
            return []
        return [f"0, 0, {redirect.group('pattern')}, 1, {target}"]

    parts = stripped.split()
    if len(parts) < 2:
        return []

    pattern = parts[0]
    action = parts[-1]
    middle = " ".join(parts[1:-1])

    if action in {"reject", "reject-img", "reject-tinygif"}:
        return [f"0, 0, {pattern}, 3"]
    if action == "reject-dict":
        return [f"0, 0, {pattern}, 2, " + quote_csv("{}")]
    if action == "reject-200":
        return [f"0, 0, {pattern}, 2, " + quote_csv(" ")]

    if "mock-response-body" in middle or action == "mock-response-body":
        data_match = re.search(r'data="([^"]*)"', middle)
        base64_match = re.search(r"mock-data-is-base64=true", middle)
        if base64_match and data_match:
            return [f"0, 0, {pattern}, 4, {data_match.group(1)}"]
        if data_match:
            return [f"0, 0, {pattern}, 2, " + quote_csv(data_match.group(1))]
        warnings.append(f"unsupported mock-response-body: {stripped[:120]}")
        return []

    if "response-body-json-del" in middle:
        path_match = re.search(r"response-body-json-del\s+(\S+)", middle)
        if path_match:
            path = path_match.group(1)
            if not path.startswith("$"):
                path = "$." + path
            return [f"1, 5, {pattern}, delete, {path}"]
        return []

    json_replace = re.search(
        r"response-body-json-replace\s+(\S+)\s+(.+)$",
        middle,
    )
    if json_replace:
        path = json_replace.group(1)
        value = json_replace.group(2).strip()
        if not path.startswith("$"):
            path = "$." + path
        return [f"1, 5, {pattern}, replace, {path}, {quote_csv(value)}"]

    jq_path = re.search(r"response-body-json-jq\s+jq-path=\"([^\"]+)\"", middle)
    if jq_path:
        try:
            jq_source = fetch_text(jq_path.group(1))
            script = jq_file_to_script(jq_source)
            if not script:
                return []
            rule = encode_script_rule(1, pattern, SHIM_PATH.read_text(encoding="utf-8") + "\n\n" + script)
            return [rule] if rule else []
        except Exception as exc:
            warnings.append(f"failed to fetch jq-path {jq_path.group(1)}: {exc}")
            return []

    jq_marker = "response-body-json-jq"
    if jq_marker in middle:
        jq_expr = middle.split(jq_marker, 1)[1].strip()
        if jq_expr.startswith(("'", '"')):
            quote = jq_expr[0]
            jq_expr = jq_expr[1:]
            end = jq_expr.rfind(quote)
            jq_expr = jq_expr[:end] if end >= 0 else jq_expr
        script = jq_inline_to_script(jq_expr)
        rule = encode_script_rule(1, pattern, SHIM_PATH.read_text(encoding="utf-8") + "\n\n" + script)
        return [rule] if rule else []

    warnings.append(f"unsupported rewrite: {stripped[:120]}")
    return []


def substitute_arguments(value: str, defaults: Dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return defaults.get(key, "")

    return re.sub(r"\{([^}]+)\}", repl, value)


def parse_script_line(
    line: str,
    defaults: Dict[str, str],
    warnings: List[str],
) -> List[str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return []

    phase = 1 if stripped.startswith("http-response") else 0 if stripped.startswith("http-request") else None
    if phase is None:
        warnings.append(f"unsupported script phase: {stripped[:120]}")
        return []

    pattern_match = re.search(r"(?:http-request|http-response)\s+(\S+?)(?=\s+script-path=)", stripped)
    if not pattern_match:
        warnings.append(f"missing script pattern: {stripped[:120]}")
        return []
    pattern = pattern_match.group(1).replace("\\/", "/")

    enable_match = re.search(r"enable=\{([^}]+)\}", stripped)
    if enable_match:
        enabled = defaults.get(enable_match.group(1), "true").lower()
        if enabled in {"false", "0", "no"}:
            return []

    script_path_match = re.search(r"script-path=([^,\s]+)", stripped)
    if not script_path_match:
        warnings.append(f"missing script-path: {stripped[:120]}")
        return []

    script_url = script_path_match.group(1)
    is_binary = "binary-body-mode=true" in stripped

    arg_match = re.search(r"argument=\[([^\]]*)\]", stripped)
    argument_defaults = dict(defaults)
    if arg_match:
        for token in re.findall(r"\{([^}]+)\}", arg_match.group(1)):
            argument_defaults.setdefault(token, defaults.get(token, ""))

    try:
        script_source = fetch_text(script_url)
    except Exception as exc:
        warnings.append(f"failed to fetch script {script_url}: {exc}")
        return []

    wrapped = wrap_external_script(script_source, argument_defaults, is_binary)
    rule = encode_script_rule(phase, pattern, wrapped)
    return [rule] if rule else []


def parse_rule_line(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("AND,") or stripped.startswith("OR,") or stripped.startswith("NOT,"):
        return None
    match = re.match(r"^(DOMAIN(?:-SUFFIX|-KEYWORD)?|DOMAIN),\s*([^,]+),\s*REJECT\b", stripped, re.I)
    if not match:
        return None
    rule_type, value = match.group(1).upper(), match.group(2).strip()
    if rule_type == "DOMAIN-KEYWORD":
        return f"3, {value}"
    return f"2, {value}"


def convert_lpx(text: str, source_name: str = "plugin") -> ConversionResult:
    lines = text.splitlines()
    meta = parse_metadata(lines)
    sections = parse_sections(text)
    defaults = parse_arguments(sections.get("argument", []))
    result = ConversionResult(name=meta.get("name") or source_name)

    mitm_lines = sections.get("mitm", [])
    for line in mitm_lines:
        match = re.match(r"^hostname\s*=\s*(.+)$", line.strip(), re.I)
        if match:
            result.hostnames.extend(split_hostname_list(match.group(1)))

    for line in sections.get("rewrite", []):
        result.rules.extend(parse_rewrite_line(line, result.warnings))

    for line in sections.get("script", []):
        result.rules.extend(parse_script_line(line, defaults, result.warnings))

    for line in sections.get("rule", []):
        routing = parse_rule_line(line)
        if routing:
            result.routing_rules.append(routing)

    return result


def render_amrs(result: ConversionResult, source_url: str = "") -> str:
    header = [
        f"name = {result.name}",
        f"hostname = {', '.join(dict.fromkeys(result.hostnames))}" if result.hostnames else "hostname = ",
        "",
        f"# Converted from: {source_url or 'local LPX'}",
        f"# Rules: {len(result.rules)}",
    ]
    if result.warnings:
        header.append(f"# Warnings: {len(result.warnings)}")
        for warning in result.warnings[:20]:
            header.append(f"# WARN: {warning}")
        if len(result.warnings) > 20:
            header.append(f"# WARN: ... and {len(result.warnings) - 20} more")
    header.append("")
    return "\n".join(header + result.rules) + "\n"


def render_arrs(name: str, rules: List[str], source_url: str = "") -> str:
    header = [
        f"name = {name} (Routing)",
        "routing = 2",
        "",
        f"# Extracted from LPX [Rule] section: {source_url}",
        "",
    ]
    return "\n".join(header + rules) + "\n"


MERGED_AMRS_NAME = "Kelee Ads"
MERGED_ARRS_NAME = "Kelee Ads (Routing)"
MERGED_AMRS_FILENAME = "KeleeAds.amrs"
MERGED_ARRS_FILENAME = "KeleeAds.arrs"


def merge_conversion_results(
    items: List[Tuple[str, ConversionResult]],
) -> Tuple[ConversionResult, ConversionResult]:
    merged_mitm = ConversionResult(name=MERGED_AMRS_NAME)
    merged_routing = ConversionResult(name=MERGED_ARRS_NAME)
    seen_hostnames: Dict[str, None] = {}
    seen_routing: Dict[str, None] = {}

    for source_url, result in items:
        for host in result.hostnames:
            if host not in seen_hostnames:
                seen_hostnames[host] = None
                merged_mitm.hostnames.append(host)
        if result.rules:
            merged_mitm.rules.append(f"# --- {result.name} ({source_url}) ---")
            merged_mitm.rules.extend(result.rules)
        if result.routing_rules:
            merged_routing.rules.append(f"# --- {result.name} ({source_url}) ---")
            for rule in result.routing_rules:
                if rule not in seen_routing:
                    seen_routing[rule] = None
                    merged_routing.rules.append(rule)
        merged_mitm.warnings.extend(
            f"{result.name}: {warning}" for warning in result.warnings
        )

    return merged_mitm, merged_routing


def render_merged_amrs(result: ConversionResult, sources: List[str]) -> str:
    header = [
        f"name = {result.name}",
        f"hostname = {', '.join(result.hostnames)}" if result.hostnames else "hostname = ",
        "",
        "# Auto-merged from Kelee Loon LPX plugins",
        f"# Sources: {len(sources)}",
    ]
    for source in sources:
        header.append(f"#   - {source}")
    header.append(f"# Rules: {sum(1 for rule in result.rules if not rule.startswith('# ---'))}")
    if result.warnings:
        header.append(f"# Warnings: {len(result.warnings)}")
        for warning in result.warnings[:30]:
            header.append(f"# WARN: {warning}")
        if len(result.warnings) > 30:
            header.append(f"# WARN: ... and {len(result.warnings) - 30} more")
    header.append("")
    return "\n".join(header + result.rules) + "\n"


def render_merged_arrs(result: ConversionResult, sources: List[str]) -> str:
    header = [
        f"name = {result.name}",
        "routing = 2",
        "",
        "# Auto-merged REJECT rules from Kelee Loon LPX plugins",
        f"# Sources: {len(sources)}",
    ]
    for source in sources:
        header.append(f"#   - {source}")
    header.append(f"# Rules: {sum(1 for rule in result.rules if not rule.startswith('# ---'))}")
    header.append("")
    return "\n".join(header + result.rules) + "\n"


def write_merged_outputs(
    items: List[Tuple[str, ConversionResult]],
    output_dir: Path,
) -> Tuple[Optional[Path], Optional[Path], List[str]]:
    merged_mitm, merged_routing = merge_conversion_results(items)
    warnings = list(merged_mitm.warnings)
    sources = [source for source, _ in items]

    amrs_path = None
    arrs_path = None

    if merged_mitm.rules:
        rule_count = sum(1 for rule in merged_mitm.rules if not rule.startswith("# ---"))
        if rule_count > MAX_RULES:
            raise RuntimeError(
                f"Merged MITM rules ({rule_count}) exceed Anywhere limit ({MAX_RULES})"
            )
        amrs_path = output_dir / MERGED_AMRS_FILENAME
        amrs_path.write_text(render_merged_amrs(merged_mitm, sources), encoding="utf-8")

    if merged_routing.rules:
        arrs_path = output_dir / MERGED_ARRS_FILENAME
        arrs_path.write_text(render_merged_arrs(merged_routing, sources), encoding="utf-8")

    return amrs_path, arrs_path, warnings


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("._")
    return cleaned or "plugin"


def convert_source(item: str) -> Tuple[str, ConversionResult]:
    if item.startswith("http://") or item.startswith("https://"):
        text = fetch_text(item)
        slug = Path(item).stem
        return item, convert_lpx(text, slug)

    path = Path(item)
    text = path.read_text(encoding="utf-8")
    return str(path), convert_lpx(text, path.stem)


def write_split_outputs(
    source_label: str,
    result: ConversionResult,
    output_dir: Path,
) -> Tuple[Optional[Path], Optional[Path], List[str]]:
    warnings = list(result.warnings)

    if len(result.rules) > MAX_RULES:
        raise RuntimeError(f"{result.name} has {len(result.rules)} MITM rules; limit is {MAX_RULES}")

    amrs_path = None
    arrs_path = None
    slug = sanitize_filename(Path(source_label).stem)

    if result.rules:
        amrs_path = output_dir / f"{slug}.amrs"
        amrs_path.write_text(render_amrs(result, source_label), encoding="utf-8")

    if result.routing_rules:
        arrs_path = output_dir / f"{slug}.arrs"
        arrs_path.write_text(render_arrs(result.name, result.routing_rules, source_label), encoding="utf-8")

    if not result.rules and not result.routing_rules:
        warnings.append("no supported rules found")

    return amrs_path, arrs_path, warnings


def convert_url(url: str, output_dir: Path) -> Tuple[Optional[Path], Optional[Path], List[str]]:
    source_label, result = convert_source(url)
    return write_split_outputs(source_label, result, output_dir)


DEFAULT_PLUGINS = [
    "https://kelee.one/Tool/Loon/Lpx/BlockAdvertisers.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Block_HTTPDNS.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Remove_ads_by_keli.lpx",
    "https://kelee.one/Tool/Loon/Lpx/RedPaper_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Bilibili_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/XiaoHeiHe_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/QiDian_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/PinDuoDuo_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/KuroBBS_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Umetrip_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/JD_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Weixin_external_links_unlock.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Weixin_Official_Accounts_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/WexinMiniPrograms_Remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/FleaMarket_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/smzdm_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/PuPuMall_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Amap_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Douyu_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/ColorfulClouds_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/BaiduNetDisk_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/Baidu_input_method_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/iQiYi_Video_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/YouTube_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/QQMusic_remove_ads.lpx",
    "https://kelee.one/Tool/Loon/Lpx/12306_remove_ads.lpx",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Loon LPX plugins to Anywhere .amrs")
    parser.add_argument("inputs", nargs="*", help="LPX file path or URL")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "MITM"),
        help="Directory for generated .amrs/.arrs files",
    )
    parser.add_argument("--batch", action="store_true", help="Convert the default Egern plugin set")
    parser.add_argument(
        "--merge",
        action="store_true",
        help=f"Also write merged {MERGED_AMRS_FILENAME} / {MERGED_ARRS_FILENAME}",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help=f"Only write merged {MERGED_AMRS_FILENAME} / {MERGED_ARRS_FILENAME}",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = list(args.inputs)
    if args.batch or not inputs:
        inputs.extend(DEFAULT_PLUGINS)

    merge_only = args.merge_only
    merge_outputs = args.merge or merge_only
    converted: List[Tuple[str, ConversionResult]] = []
    failures = 0

    for item in inputs:
        try:
            source_label, result = convert_source(item)
            converted.append((source_label, result))

            if merge_only:
                warnings = list(result.warnings)
                print(f"[ok] {source_label}")
                for warning in warnings[:3]:
                    print(f"     warn: {warning}")
                if len(warnings) > 3:
                    print(f"     warn: ... {len(warnings) - 3} more")
                if not result.rules and not result.routing_rules:
                    failures += 1
                continue

            amrs_path, arrs_path, warnings = write_split_outputs(source_label, result, output_dir)
            print(f"[ok] {source_label}")
            if amrs_path:
                print(f"     amrs -> {amrs_path}")
            if arrs_path:
                print(f"     arrs -> {arrs_path}")
            for warning in warnings[:5]:
                print(f"     warn: {warning}")
            if len(warnings) > 5:
                print(f"     warn: ... {len(warnings) - 5} more")
            if not amrs_path and not arrs_path:
                failures += 1
        except Exception as exc:
            failures += 1
            print(f"[fail] {item}: {exc}", file=sys.stderr)

    if merge_outputs and converted:
        try:
            amrs_path, arrs_path, warnings = write_merged_outputs(converted, output_dir)
            print(f"[merge] {len(converted)} plugins")
            if amrs_path:
                print(f"     amrs -> {amrs_path}")
            if arrs_path:
                print(f"     arrs -> {arrs_path}")
            for warning in warnings[:5]:
                print(f"     warn: {warning}")
            if len(warnings) > 5:
                print(f"     warn: ... {len(warnings) - 5} more")
            if not amrs_path and not arrs_path:
                failures += 1
        except Exception as exc:
            failures += 1
            print(f"[fail] merge: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())