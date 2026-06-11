# APNS 规则转换

来源：https://raw.githubusercontent.com/QuixoticHeart/rule-set/refs/heads/ruleset/loon/apns.list

推荐订阅地址：https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/APNS.arrs

用途：这份规则建议单独订阅，并把 `Route To` 设置为代理。

已转换规则数：13

转换规则：

- `DOMAIN` -> `2, value`：1 条。Anywhere 当前没有精确域名类型，所以映射为域名后缀，匹配范围会略宽。
- `DOMAIN-SUFFIX` -> `2, value`：2 条。
- `DOMAIN-KEYWORD` -> `3, value`：1 条。
- `IP-CIDR` -> `0, value`：5 条。
- `IP-CIDR6` -> `1, value`：4 条。
- 跳过其他不支持规则：0 条。
