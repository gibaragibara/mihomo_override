/*
 * po0 防火墙自动加白 · Egern
 *
 * - schedule / network：静默加白，仅状态变化时 notify
 * - generic / widget：返回与「服务器监控」同风格的小组件 DSL
 *
 * env_schema → ctx.env:
 *   tokens  pgnfw_…（可逗号多台；单条可 pgnfw_xxx@N）
 *   slot    坑位索引，从 0 起算（0=第1坑，2=第3坑）；空=不固定
 */

const API_BASE = "https://124.221.69.228/api/firewall/";
const STORE_PREFIX = "po0_fw_";
const HIST_WINDOW_MS = 24 * 3600 * 1000;

const C = {
  bg1: "#1C1C1E",
  bg2: "#2C2C2E",
  text: "#FFFFFF",
  muted: "#8E8E93",
  dim: "#636366",
  ok: "#30D158",
  bad: "#FF453A",
  warn: "#FFD60A",
  accent: "#0A84FF",
  pin: "#64D2FF",
};

function parseGlobalSlot(raw) {
  if (raw === null || raw === undefined) return null;
  const s = String(raw).trim();
  if (!s) return null;
  const n = parseInt(s, 10);
  return Number.isNaN(n) ? null : n;
}

function parseTokens(raw, defaultSlot) {
  return String(raw || "")
    .split(/[,|;、\s]+/)
    .map((s) => s.trim())
    .filter((s) => s.indexOf("pgnfw_") === 0)
    .map((s) => {
      const at = s.indexOf("@");
      if (at === -1) return { token: s, slot: defaultSlot };
      const n = parseInt(s.slice(at + 1), 10);
      return { token: s.slice(0, at), slot: Number.isNaN(n) ? defaultSlot : n };
    });
}

function onCellular(ctx) {
  try {
    const d = ctx.device || {};
    const onWifi = !!(d.wifi && d.wifi.ssid);
    const hasCell = !!(d.cellular && (d.cellular.carrier || d.cellular.radio));
    return !onWifi && hasCell;
  } catch (e) {
    return false;
  }
}

function readHistory(ctx, key) {
  let h;
  try {
    h = ctx.storage.getJSON(key) || [];
  } catch (e) {
    h = [];
  }
  if (!Array.isArray(h)) h = [];
  const cutoff = Date.now() - HIST_WINDOW_MS;
  return h.filter((e) => e && e.ts > cutoff);
}

function sameC24(a, b) {
  if (!a || !b) return false;
  a = String(a);
  b = String(b);
  if (a === b) return true;
  if (a.slice(-3) !== "/24" && b.slice(-3) !== "/24") return false;
  const pa = a.replace("/24", "").split(".");
  const pb = b.replace("/24", "").split(".");
  return (
    pa.length === 4 &&
    pb.length === 4 &&
    pa[0] === pb[0] &&
    pa[1] === pb[1] &&
    pa[2] === pb[2]
  );
}

async function apiCall(ctx, token, slot) {
  let url = API_BASE + encodeURIComponent(token) + "/add";
  if (slot !== null && slot !== undefined && slot !== "") {
    url += "?slot=" + encodeURIComponent(slot);
  }
  let resp;
  try {
    resp = await ctx.http.post(url, {
      headers: { "Content-Type": "application/json" },
      body: "",
      timeout: 15000,
    });
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
  let text = "";
  try {
    text = await resp.text();
  } catch (e) {}
  let data = null;
  try {
    data = JSON.parse(text);
  } catch (e) {}
  if (resp.status === 403) {
    return {
      error: "槽位冲突：本机 IP 已在其它槽位",
      conflict: true,
      currentIp: data && data.currentIp,
    };
  }
  if (!data) return { error: "响应异常: " + String(text).slice(0, 80) };

  const raw = Array.isArray(data.whitelist) ? data.whitelist : [];
  data.slotOf = {};
  raw.forEach((e) => {
    if (e && typeof e === "object" && e.slot !== null && e.slot !== undefined) {
      data.slotOf[e.ip] = e.slot;
    }
  });
  data.whitelist = raw.map((e) => (e && typeof e === "object" ? e.ip : e));
  data.applied =
    data.enabled === true &&
    data.whitelist.some((ip) => sameC24(ip, data.currentIp));
  return data;
}

async function ensure(ctx, item, index, cellular) {
  const kvState = STORE_PREFIX + index;
  const kvHist = STORE_PREFIX + "hist_" + index;
  const st = await apiCall(ctx, item.token, item.slot);
  if (st.applied) {
    const hist = readHistory(ctx, kvHist);
    const last = hist.length ? hist[hist.length - 1] : null;
    if (!last || last.ip !== st.currentIp) {
      hist.push({ ip: st.currentIp, src: cellular ? "cell" : "fixed", ts: Date.now() });
      ctx.storage.setJSON(kvHist, hist.slice(-10));
    }
  }
  return { kvState, kvHist, slot: item.slot, st };
}

function describeNotify(ctx, index, c) {
  const st = c.st;
  const pin = c.slot !== null && c.slot !== undefined && c.slot !== "" ? " 📌" + c.slot : "";
  const head = "#" + (index + 1) + pin + " ";
  if (st.error) return head + "❌ " + st.error;
  if (st.enabled === false) return head + "⚠️ 防火墙未启用";
  if (!st.applied) {
    return head + "❌ 加白未生效 " + ((st.whitelist && st.whitelist.length) || 0) + "/" + st.limit;
  }
  const hist = readHistory(ctx, c.kvHist);
  const cellIps = {};
  hist.forEach((e) => {
    if (e.src === "cell") cellIps[e.ip] = true;
  });
  const slotOf = st.slotOf || {};
  const ips = st.whitelist
    .map((ip) => {
      const slotTag = slotOf[ip] !== undefined ? " 📌" + slotOf[ip] : "";
      return ip + slotTag + (cellIps[ip] ? " 📶" : "") + (sameC24(ip, st.currentIp) ? " ←" : "");
    })
    .join("\n    ");
  return head + "✅ " + st.whitelist.length + "/" + st.limit + "\n    " + ips;
}

/** 汇总 UI 数据 */
function buildView(ctx, results, cellular) {
  let okCount = 0;
  let exitIp = "?";
  const machines = [];

  results.forEach((c, i) => {
    const st = c.st;
    if (st.applied) okCount++;
    if (st.currentIp) exitIp = st.currentIp;

    const hist = readHistory(ctx, c.kvHist);
    const cellIps = {};
    hist.forEach((e) => {
      if (e.src === "cell") cellIps[e.ip] = true;
    });

    let status = "ok";
    let statusText = "OK";
    if (st.error) {
      status = "bad";
      statusText = st.error;
    } else if (st.enabled === false) {
      status = "warn";
      statusText = "防火墙未启用";
    } else if (!st.applied) {
      status = "bad";
      statusText = "加白未生效";
    }

    const entries = [];
    if (Array.isArray(st.whitelist)) {
      st.whitelist.forEach((ip) => {
        entries.push({
          ip,
          slot: st.slotOf && st.slotOf[ip] !== undefined ? st.slotOf[ip] : null,
          cell: !!cellIps[ip],
          current: sameC24(ip, st.currentIp),
        });
      });
    }

    machines.push({
      index: i + 1,
      pinSlot: c.slot,
      status,
      statusText,
      used: (st.whitelist && st.whitelist.length) || 0,
      limit: st.limit != null ? st.limit : "?",
      entries,
      error: st.error || null,
    });
  });

  return {
    ok: okCount === results.length && okCount > 0,
    okCount,
    total: results.length,
    exitIp,
    cellular,
    machines,
  };
}

function divider() {
  return {
    type: "stack",
    direction: "row",
    height: 1,
    backgroundColor: "#3A3A3C",
    children: [{ type: "spacer" }],
  };
}

function textNode(text, opts = {}) {
  const font = {
    size: opts.size || "caption1",
    weight: opts.weight || "medium",
  };
  if (opts.mono) font.family = "Menlo";
  return {
    type: "text",
    text: String(text),
    font,
    textColor: opts.color || C.text,
    maxLines: opts.maxLines || 2,
    minScale: opts.minScale || 0.75,
  };
}

function row(children, gap = 4) {
  return {
    type: "stack",
    direction: "row",
    alignItems: "center",
    gap,
    children,
  };
}

function col(children, gap = 3) {
  return {
    type: "stack",
    direction: "column",
    gap,
    children,
  };
}

function statusColor(status) {
  if (status === "ok") return C.ok;
  if (status === "warn") return C.warn;
  return C.bad;
}

function header(v) {
  const color = v.ok ? C.ok : C.bad;
  return row(
    [
      {
        type: "image",
        src: v.ok ? "sf-symbol:checkmark.shield.fill" : "sf-symbol:exclamationmark.shield.fill",
        width: 14,
        height: 14,
        color,
      },
      textNode(`po0 加白 ${v.okCount}/${v.total}`, {
        size: "subheadline",
        weight: "bold",
        color: C.text,
        maxLines: 1,
      }),
      { type: "spacer" },
      textNode(v.cellular ? "蜂窝" : "出口", {
        size: "caption2",
        color: C.dim,
        maxLines: 1,
      }),
    ],
    6
  );
}

function exitRow(v) {
  return row(
    [
      {
        type: "image",
        src: "sf-symbol:network",
        width: 12,
        height: 12,
        color: C.accent,
      },
      textNode(String(v.exitIp), {
        size: "caption1",
        weight: "semibold",
        mono: true,
        color: C.accent,
        maxLines: 1,
      }),
      { type: "spacer" },
      textNode(v.ok ? "已加白" : "异常", {
        size: "caption2",
        weight: "bold",
        color: v.ok ? C.ok : C.bad,
        maxLines: 1,
      }),
    ],
    6
  );
}

function machineBlock(m, compact) {
  const color = statusColor(m.status);
  const pin =
    m.pinSlot !== null && m.pinSlot !== undefined && m.pinSlot !== ""
      ? ` 钉#${m.pinSlot}`
      : "";
  const head = `#${m.index}${pin}  ${m.used}/${m.limit}  ${m.statusText}`;

  const lines = [
    row(
      [
        {
          type: "image",
          src:
            m.status === "ok"
              ? "sf-symbol:checkmark.circle.fill"
              : m.status === "warn"
                ? "sf-symbol:exclamationmark.triangle.fill"
                : "sf-symbol:xmark.circle.fill",
          width: 12,
          height: 12,
          color,
        },
        textNode(head, {
          size: "caption1",
          weight: "semibold",
          color: C.text,
          maxLines: 1,
        }),
      ],
      4
    ),
  ];

  if (m.entries && m.entries.length) {
    const show = compact ? m.entries.slice(0, 3) : m.entries;
    show.forEach((e) => {
      const tags = [];
      if (e.slot !== null && e.slot !== undefined) tags.push(`#${e.slot}`);
      if (e.cell) tags.push("cell");
      if (e.current) tags.push("<-");
      const suffix = tags.length ? "  " + tags.join(" ") : "";
      lines.push(
        textNode(`  ${e.ip}${suffix}`, {
          size: 11,
          mono: true,
          color: e.current ? C.pin : C.muted,
          maxLines: 1,
        })
      );
    });
    if (compact && m.entries.length > 3) {
      lines.push(
        textNode(`  +${m.entries.length - 3} more`, {
          size: 10,
          color: C.dim,
          maxLines: 1,
        })
      );
    }
  } else if (m.error) {
    lines.push(
      textNode(`  ${m.error}`, {
        size: 11,
        color: C.bad,
        maxLines: 2,
      })
    );
  }

  return col(lines, 2);
}

function emptyWidget(message) {
  return {
    type: "widget",
    backgroundColor: C.bg1,
    padding: 14,
    gap: 8,
    children: [
      row(
        [
          {
            type: "image",
            src: "sf-symbol:exclamationmark.shield.fill",
            width: 16,
            height: 16,
            color: C.bad,
          },
          textNode("po0 防火墙加白", {
            size: "headline",
            weight: "bold",
            color: C.text,
          }),
        ],
        6
      ),
      textNode(message, {
        size: "caption1",
        color: C.muted,
        maxLines: 4,
      }),
    ],
  };
}

function renderWidget(v, family) {
  const refreshAfter = new Date(Date.now() + 10 * 60 * 1000).toISOString();

  // 锁屏内联
  if (family === "accessoryInline") {
    return {
      type: "widget",
      children: [
        textNode(
          v.ok ? `po0 ${v.okCount}/${v.total} ${v.exitIp}` : `po0 异常`,
          { size: "caption1", weight: "semibold", mono: true, maxLines: 1 }
        ),
      ],
    };
  }

  // 锁屏圆形
  if (family === "accessoryCircular") {
    return {
      type: "widget",
      padding: 4,
      children: [
        col(
          [
            {
              type: "image",
              src: v.ok
                ? "sf-symbol:checkmark.shield.fill"
                : "sf-symbol:exclamationmark.shield.fill",
              width: 18,
              height: 18,
              color: v.ok ? C.ok : C.bad,
            },
            textNode(`${v.okCount}/${v.total}`, {
              size: "caption2",
              weight: "bold",
              mono: true,
              color: C.text,
              maxLines: 1,
            }),
          ],
          2
        ),
      ],
    };
  }

  // 锁屏矩形
  if (family === "accessoryRectangular") {
    return {
      type: "widget",
      gap: 2,
      children: [
        textNode(`po0 ${v.okCount}/${v.total}`, {
          size: "headline",
          weight: "bold",
          maxLines: 1,
        }),
        textNode(String(v.exitIp), {
          size: 11,
          mono: true,
          color: C.muted,
          maxLines: 1,
        }),
        textNode(v.ok ? "已加白" : "异常", {
          size: "caption2",
          color: v.ok ? C.ok : C.bad,
          maxLines: 1,
        }),
      ],
    };
  }

  // 小尺寸
  if (family === "systemSmall") {
    const m0 = v.machines[0];
    return {
      type: "widget",
      backgroundColor: C.bg1,
      padding: 12,
      gap: 6,
      refreshAfter,
      children: [
        header(v),
        divider(),
        textNode(String(v.exitIp), {
          size: "caption1",
          weight: "bold",
          mono: true,
          color: C.accent,
          maxLines: 1,
        }),
        textNode(
          m0
            ? `#${m0.index} ${m0.used}/${m0.limit} ${m0.statusText}`
            : "-",
          {
            size: 11,
            mono: true,
            color: C.muted,
            maxLines: 2,
          }
        ),
      ],
    };
  }

  // 中尺寸（对齐服务器监控 systemMedium）
  if (family === "systemMedium") {
    const blocks = v.machines.map((m) => machineBlock(m, true));
    return {
      type: "widget",
      backgroundColor: C.bg1,
      padding: [10, 14],
      gap: 6,
      refreshAfter,
      children: [header(v), exitRow(v), divider(), ...blocks],
    };
  }

  // 大尺寸 / 默认（对齐服务器监控 large）
  const blocks = v.machines.map((m) => machineBlock(m, false));
  return {
    type: "widget",
    backgroundColor: C.bg1,
    padding: [12, 14],
    gap: 6,
    refreshAfter,
    children: [
      header(v),
      exitRow(v),
      divider(),
      ...blocks,
      {
        type: "stack",
        direction: "row",
        children: [
          { type: "spacer" },
          textNode("每 10 分钟 / 切网自动加白", {
            size: "caption2",
            color: C.dim,
            maxLines: 1,
          }),
        ],
      },
    ],
  };
}

export default async function (ctx) {
  const env = ctx.env || {};
  const defaultSlot = parseGlobalSlot(env.slot);
  const tokens = parseTokens(env.tokens || env.token, defaultSlot);
  const isWidget = !!ctx.widgetFamily;

  if (tokens.length === 0) {
    const msg = "请在模块参数填写 Token；可选填写坑位（0=第1坑，2=第3坑）";
    if (!isWidget) {
      ctx.notify({
        title: "po0 防火墙加白",
        subtitle: "未配置 token",
        body: msg,
      });
      return;
    }
    return emptyWidget(msg);
  }

  const cellular = onCellular(ctx);
  const results = [];
  for (let i = 0; i < tokens.length; i++) {
    results.push(await ensure(ctx, tokens[i], i, cellular));
  }

  let changed = false;
  const notifyLines = [];
  for (let i = 0; i < results.length; i++) {
    const st = results[i].st;
    notifyLines.push(describeNotify(ctx, i, results[i]));
    const state = (st.currentIp || "?") + "|" + (st.applied ? "1" : "0");
    if (ctx.storage.get(results[i].kvState) !== state) {
      ctx.storage.set(results[i].kvState, state);
      changed = true;
    }
  }

  const v = buildView(ctx, results, cellular);
  const title = `po0 加白 ${v.okCount}/${v.total} · 出口 ${v.exitIp}${cellular ? " 📶" : ""}`;

  // cron / network：只通知，不返回 widget
  if (!isWidget) {
    if (changed) {
      ctx.notify({
        title: "po0 防火墙加白",
        subtitle: title,
        body: notifyLines.join("\n"),
      });
    }
    return;
  }

  // generic / 小组件：按尺寸返回 DSL（对齐服务器监控）
  try {
    return renderWidget(v, ctx.widgetFamily);
  } catch (e) {
    return emptyWidget("渲染失败: " + String((e && e.message) || e));
  }
}
