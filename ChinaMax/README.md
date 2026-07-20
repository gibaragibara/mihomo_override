# ChinaMax 规则转换

来源：https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/ChinaMax/ChinaMax.list

说明：`ChinaMax.yaml` 只包含较小的 payload 子集，这里使用 `ChinaMax.list` 完整列表转换。

推荐订阅地址（需要全部导入）：

- https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/ChinaMax/ChinaMax-001.arrs
- https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/ChinaMax/ChinaMax-002.arrs

已转换规则数：124587

分片数量：2

单个分片规则上限：100000

转换规则：

- `DOMAIN` -> `2, value`：295 条。Anywhere 当前没有精确域名类型，所以映射为域名后缀，匹配范围会略宽。
- `DOMAIN-SUFFIX` -> `2, value`：111843 条。
- `DOMAIN-KEYWORD` -> `3, value`：13 条。
- `IP-CIDR` -> `0, value`：8226 条。
- `IP-CIDR6` -> `1, value`：4210 条。
- 跳过 `PROCESS-NAME`：14 条。
- 跳过 `IP-ASN`：1 条。
- 跳过其他不支持规则：0 条。

使用方式：在 Anywhere 的 Routing Rules 里导入上面的全部 `ChinaMax-*.arrs`，然后把每个规则集的 `Route To` 设置为 `DIRECT`。

自动更新：仓库中的 GitHub Actions 会每天运行一次 `scripts/update_chinamax.py`，拉取上游 `ChinaMax.list` 重新转换；如果结果有变化，会自动提交到 `main`。
