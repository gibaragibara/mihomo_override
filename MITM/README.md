# Kelee LPX → Anywhere MITM

把 [Kelee](https://hub.kelee.one) 的 Loon `.lpx` 去广告插件自动转换成 Anywhere 可用的合并规则集。

## 订阅地址（推荐）

MITM 规则（设置 → MITM → 订阅）：

```
https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/MITM/KeleeAds.amrs
```

配套路由 REJECT 规则（Routing Rules → 订阅，Route To 设为 **REJECT**）：

```
https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/MITM/KeleeAds.arrs
```

Deep Link 一键导入：

```
anywhere://add-rule-set?link=https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/MITM/KeleeAds.amrs&link=https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/MITM/KeleeAds.arrs
```

## 使用前提

1. 设置 → **MITM** → 打开开关
2. 安装并信任 **Root Certificate**
3. 订阅上面的 `KeleeAds.amrs`
4. （可选）订阅 `KeleeAds.arrs` 并在 Routing Rules 里设为 REJECT

## 自动更新

GitHub Actions 每天 UTC 04:23 运行 `scripts/plugin2amrs.py --batch --merge-only`：

- 从 kelee.one 拉取最新 LPX 插件
- 转换成 Anywhere 格式
- 合并写入 `KeleeAds.amrs` / `KeleeAds.arrs`
- 有变化时自动提交到 `main`

也可在 GitHub → Actions → **Update Kelee MITM** 手动触发。

## 本地重新生成

```bash
python3 scripts/plugin2amrs.py --batch --merge-only
```

转换单个插件并查看拆分结果：

```bash
python3 scripts/plugin2amrs.py https://kelee.one/Tool/Loon/Lpx/Bilibili_remove_ads.lpx
python3 scripts/plugin2amrs.py --batch --merge
```

## 转换说明

| Loon LPX | Anywhere |
|----------|----------|
| `[MitM] hostname` | `hostname = ...` |
| `reject` / `reject-dict` | rewrite 拦截（GIF / 空 JSON） |
| `mock-response-body` | rewrite 200 响应 |
| `response-body-json-del/replace` | `body-json` 原生规则 |
| `response-body-json-jq` | JavaScript 脚本 |
| `[Script] script-path=...` | 带 Surge/Loon 兼容层的 `script` 规则 |
| `[Rule] ... REJECT` | 合并进 `KeleeAds.arrs` |

## 已知限制

- 合并后约 425 条 MITM 规则、443 条路由规则，远低于 Anywhere 单文件上限。
- **复杂 JQ 表达式**、**Protobuf 脚本**、**307 重定向带捕获组**（QQ_Redirect）等个别规则可能无法转换。
- 生成文件顶部的 `# WARN:` 注释会列出未能自动转换的规则。