# Apple 规则转换

用户提供来源：https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Surge/Apple/Apple.list

实际转换来源：https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Apple/Apple.list

说明：用户提供的 Surge 文件头部声明包含 1551 条 `DOMAIN-SUFFIX`，但文件正文实际缺少这些域名后缀规则；同仓库的 Clash Apple 文件包含完整规则，所以这里使用 Clash 版本转换。

推荐订阅地址：https://raw.githubusercontent.com/gibaragibara/mihomo_override/main/Apple.arrs

用途：这份 Apple 规则建议设置为 `DIRECT`。APNS 相关规则已从这里移除，请单独订阅 `APNS.arrs` 并设置为代理。

已转换规则数：1578
已移除 APNS 重叠规则：2

转换规则：

- `DOMAIN` -> `2, value`：9 条。Anywhere 当前没有精确域名类型，所以映射为域名后缀，匹配范围会略宽。
- `DOMAIN-SUFFIX` -> `2, value`：1550 条。
- `DOMAIN-KEYWORD` -> `3, value`：6 条。
- `IP-CIDR` -> `0, value`：10 条。
- `IP-CIDR6` -> `1, value`：3 条。
- 跳过 `PROCESS-NAME`：13 条。
- 跳过其他不支持规则：0 条。

注意：Apple 源规则中仍包含较宽的 Apple IP 段，例如 `17.0.0.0/8`。APNS 规则里的更具体 CIDR 在同一 User tier 中会按最长前缀优先命中。
