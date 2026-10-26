# Skills

yujiangxian 常用的 Claude Code 技能合集。按插件组织，每个技能可以单独安装、单独更新。

## 收录

| 插件 | 技能 | 用途 |
|---|---|---|
| [product-tree](plugins/product-tree/) | `product-tree` | 用一棵树管住整个产品设计，防止同一件事在代码里被做几套 |
| [browser-skill](plugins/browser-skill/) | `browser-skill` | 操作用户已登录的 Chromium 浏览器：读页面、填表单、抓数据、测 UI |
| [taste-skill](plugins/taste-skill/) | `design-taste-frontend` | 前端设计品味：从研究过的方向库取方向，在真实浏览器里检查并迭代页面 |
| [dingtalk](plugins/dingtalk/) | `dingtalk:*`（14 个） | 钉钉 DWS 技能集合：消息、文档、日历、待办、审批、通讯录、AI 表格等 |
| [wecomcli](plugins/wecomcli/) | `wecomcli:*`（14 个） | 企业微信 CLI 技能集合：消息、文档、日程、会议、邮件、待办、微盘等 |

## 安装

在 Claude Code 中先添加市场，再按需安装：

```text
/plugin marketplace add yujiangxian/hello_skills
/plugin install product-tree@hello-skills
```

其余两个插件同理：

```text
/plugin install browser-skill@hello-skills
/plugin install taste-skill@hello-skills
/plugin install dingtalk@hello-skills
/plugin install wecomcli@hello-skills
```

`dingtalk` 需要本机安装 `dws` CLI，`wecomcli` 需要 `wecom-cli`；技能本身不含 CLI。

安装后技能以 `插件名:技能名` 调用，例如 `product-tree:product-tree`、`taste-skill:design-taste-frontend`。

更新：

```text
/plugin marketplace update hello-skills
/plugin update product-tree@hello-skills
```

## 目录结构

```text
.
├── .claude-plugin/
│   └── marketplace.json          # 市场目录：列出所有插件
├── plugins/
│   ├── product-tree/
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json       # 插件清单
│   │   ├── README.md
│   │   └── skills/
│   │       └── product-tree/     # SKILL.md 与脚本、模板
│   ├── browser-skill/
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json
│   │   └── skills/
│   │       └── browser-skill/
│   ├── taste-skill/
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json
│   │   ├── LICENSE               # 上游 MIT 许可证
│   │   └── skills/
│   │       └── design-taste-frontend/
│   ├── dingtalk/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── README.md
│   │   └── skills/dingtalk-*/    # 14 个技能
│   └── wecomcli/
│       ├── .claude-plugin/plugin.json
│       ├── README.md
│       └── skills/wecomcli-*/    # 14 个技能
└── .github/workflows/check.yml   # product-tree 脚本与示例树的检查
```

## 不用插件市场

把需要的技能目录复制到 `~/.claude/skills/`（个人级）或项目的 `.claude/skills/`（项目级）：

```bash
cp -r plugins/product-tree/skills/product-tree ~/.claude/skills/
```

## 添加新技能

1. 新建 `plugins/<插件名>/skills/<技能名>/SKILL.md`，其中 `name` 与目录名一致；
2. 新建 `plugins/<插件名>/.claude-plugin/plugin.json`；
3. 在 `.claude-plugin/marketplace.json` 的 `plugins` 数组里加一条，`source` 写 `./plugins/<插件名>`；
4. 用 `claude plugin validate ./plugins/<插件名>` 和 `claude plugin validate .` 自检。

一个插件可以放多个技能：在 `skills/` 下并列多个目录即可，安装时一起生效。需要独立版本节奏的技能才拆成单独插件。

## 许可

- 本仓库与 `product-tree`、`browser-skill`：MIT，见 [LICENSE](LICENSE)
- `taste-skill`：MIT，版权归 [Leonxlnx](https://github.com/Leonxlnx)，见 [plugins/taste-skill/LICENSE](plugins/taste-skill/LICENSE)
- `dingtalk`、`wecomcli`：收录自本机 CLI 分发目录的快照，未附独立许可证，版权归对应平台；上游更新以官方分发为准。
