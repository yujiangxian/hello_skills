# dingtalk

钉钉（DWS）技能集合，共 16 个技能。安装后以 `dingtalk:<技能名>` 调用。

## 前置条件

需要本机已安装并登录 [DWS CLI](https://open.dingtalk.com/)（`dws`）。技能本身只是一组命令约定和参考文档，不包含 CLI。

## 收录的技能

| 技能 | 用途 |
|---|---|
| `dingtalk-aicard` | 离线创建、编辑与校验钉钉 AI Card（A2UI）JSON |
| `dingtalk-aisearch` | AI搜问：人员语义搜索、跨源内容定位与行为回溯 |
| `dingtalk-aitable` | 钉钉 AI 表格（多维表） |
| `dingtalk-calendar` | 钉钉日历与会议室 |
| `dingtalk-chat` | 钉钉群聊与消息 |
| `dingtalk-contact` | 钉钉通讯录精确查询 |
| `dingtalk-doc` | 钉钉在线文字文档（adoc） |
| `dingtalk-drive` | 钉盘与文档空间的文件管理 |
| `dingtalk-event` | IM、审批、待办与互动卡片事件监听 |
| `dingtalk-mail` | 钉钉邮箱读写、搜索、回复与转发 |
| `dingtalk-minutes` | 钉钉 AI 听记 |
| `dingtalk-misc` | 长尾产品：OA 审批、合同、考勤、直播、Agoal、日志、白板、招聘等 |
| `dingtalk-shared` | DWS 多技能共享入口与产品边界消歧 |
| `dingtalk-tag` | 钉钉数字员工的创建、查询、发布与能力管理 |
| `dingtalk-todo` | 钉钉待办 |
| `dingtalk-wiki` | 钉钉知识库与空间管理 |

## 来源与许可

技能随 npm 包 `dingtalk-workspace-cli` 发布，取自包内的 `share/skills/multi`（旧版）或 `assets/dws-skills.zip`（1.0.63+）。版权归 Alibaba Group，按 Apache License 2.0 分发，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

仓库每周自动检查上游 npm 包，有更新时创建 PR。
