# MoviePilot-Plugin-Market

MoviePilot第三方插件市场：https://github.com/Aqr-k/MoviePilot-Plugins/

### 插件列表

| 序号 |                名称                | 当前版本 | 功能简述                                         | 用户级别 |
|:--:|:--------------------------------:|:----:|:---------------------------------------------|:----:|
| 1  |  [SMTP邮件消息通知](docs/SmtpMsg.md)   | v3.0 | 支持使用邮件服务器发送消息通知。                             | 无需认证 |
| 2  | [自定义消息汇报](docs/SendCustomMsg.md) | v1.2 | 支持手动发送自定义消息，也可用于调试各类消息通知插件。                  | 无需认证 |
| 3  |  [MQTT消息交互](docs/MqttClient.md)  | v0.2 | 可接入HomeAssistant，支持使用智能家居设备，汇报状态信息。          | 无需认证 |
| 4  |   [云盘拓展功能](docs/CloudHelperPlus.md)   | v2.7 | 拓展官方内置支持的云盘的部分功能，功能开放API接口。                  | 需要认证 |
| 5  |  [用户管理拓展功能](docs/UserSettingPlus.md)  | v1.4 | 支持快速添加新的超级管理员；支持管理用户权限等级、用户名、用户密码、用户状态、用户邮箱。 | 无需认证 |
| 6  |  [钉钉机器人消息通知](/docs/DingTalkBotMsg.md)  | v1.5 | 支持使用钉钉群聊机器人发送消息通知。                           | 无需认证 |
| 7  |  [Server酱消息通知](/docs/ServerChanMsg.md)  | v1.1 | 支持使用Server酱发送消息通知。                           | 无需认证 |
| 8  |  [插件库更新推送](/docs/PluginMarketsAutoUpdate.md)  | v2.0 | 支持从官方Wiki中获取记录的最新全量插件库、结合添加黑名单，自动化添加插件库。     | 无需认证 |
| 9  |  [PIP依赖包检测与安装](/docs/PipDetectionInstall.md)  | v1.0 | 解决MoviePilot 的PIP依赖包下载超时失败、不支持代理导致下载缓慢等问题。   | 无需认证 |
| 10 | [自动订阅助手](plugins.v3/automaticsubscriptionassistant/README.md) | v3.2.0 | 聚合五类榜单来源，按媒体身份与季号自动订阅，支持黑名单、独立侧栏和仪表盘概览。 | 需要认证 |

自动订阅助手后续仅维护、测试和发布 MoviePilot v3 版本；v2 保留历史版本。插件文档说明当前源码行为，未发布的新功能请以对应 Release 为准。

### 特别鸣谢
- [MoviePilot](https://github.com/jxxghp/MoviePilot)
- [jxxghp](https://github.com/jxxghp)
- [thsrite](https://github.com/thsrite)
- [InfinityPacer](https://github.com/InfinityPacer)
