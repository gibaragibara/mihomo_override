# China 规则转换

来源：https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/China/China.list

推荐订阅地址：https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/China.arrs

已转换规则数：3723

转换规则：

- `DOMAIN` -> `2, value`：17 条。Anywhere 当前没有精确域名类型，所以映射为域名后缀，匹配范围会略宽。
- `DOMAIN-SUFFIX` -> `2, value`：3676 条。
- `DOMAIN-KEYWORD` -> `3, value`：9 条。
- `IP-CIDR` -> `0, value`：17 条。
- `IP-CIDR6` -> `1, value`：4 条。
- 跳过其他不支持规则：0 条。

使用方式：在 Anywhere 的 Routing Rules 里导入 `China.arrs`，然后把该规则集的 `Route To` 设置为 `DIRECT`。
