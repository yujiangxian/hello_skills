#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Git Bash 的 /tmp 对 Windows 版 Node 不可见，转成 C:/... 形式；CI 里没有 cygpath，原样返回。
node_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s' "$1"
  fi
}

echo "==> DingTalk: dingtalk-workspace-cli@latest"
mkdir -p "$TMP/dingtalk"
npm pack dingtalk-workspace-cli@latest --pack-destination "$TMP/dingtalk" >/dev/null
tar -xzf "$TMP"/dingtalk/dingtalk-workspace-cli-*.tgz -C "$TMP/dingtalk"
DINGTALK_VERSION=$(node -p "require('$(node_path "$TMP/dingtalk/package/package.json")').version")

# 1.0.63+ 把技能放在 assets/dws-skills.zip；更早的版本直接放在 share/skills。
DINGTALK_ZIP="$TMP/dingtalk/package/assets/dws-skills.zip"
if [ -f "$DINGTALK_ZIP" ]; then
  mkdir -p "$TMP/dingtalk/skills"
  PY=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys' >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
  [ -n "$PY" ] || { echo "python is required to unpack dws-skills.zip" >&2; exit 1; }
  "$PY" -m zipfile -e "$(node_path "$DINGTALK_ZIP")" "$(node_path "$TMP/dingtalk/skills")"
  DINGTALK_SRC="$TMP/dingtalk/skills"
else
  DINGTALK_SRC="$TMP/dingtalk/package/share/skills"
fi

rm -rf plugins/dingtalk/skills
mkdir -p plugins/dingtalk/skills
cp -R "$DINGTALK_SRC/multi/." plugins/dingtalk/skills/
cp "$DINGTALK_SRC/LICENSE" plugins/dingtalk/LICENSE
if [ -f "$DINGTALK_SRC/NOTICE" ]; then
  cp "$DINGTALK_SRC/NOTICE" plugins/dingtalk/NOTICE
elif [ -f "$DINGTALK_SRC/mono/NOTICE" ]; then
  cp "$DINGTALK_SRC/mono/NOTICE" plugins/dingtalk/NOTICE
fi

echo "==> WeCom: WecomTeam/wecom-cli@main"
curl -fsSL "https://api.github.com/repos/WecomTeam/wecom-cli/tarball/main" -o "$TMP/wecom.tgz"
mkdir -p "$TMP/wecom"
tar -xzf "$TMP/wecom.tgz" -C "$TMP/wecom" --strip-components=1
WECOM_VERSION=$(node -p "require('$(node_path "$TMP/wecom/package.json")').version")

rm -rf plugins/wecomcli/skills
mkdir -p plugins/wecomcli/skills
cp -R "$TMP/wecom/skills/." plugins/wecomcli/skills/
cp "$TMP/wecom/LICENSE" plugins/wecomcli/LICENSE

# 上游可能带可执行位，统一成普通文件，避免每次同步只产生 mode 变更。
find plugins/dingtalk/skills plugins/wecomcli/skills -type f -exec chmod 644 {} +

echo "==> Updating plugin versions"
DINGTALK_VERSION="$DINGTALK_VERSION" WECOM_VERSION="$WECOM_VERSION" node <<'JS'
const fs = require('fs');
const versions = {
  dingtalk: process.env.DINGTALK_VERSION,
  wecomcli: process.env.WECOM_VERSION,
};
for (const [name, version] of Object.entries(versions)) {
  const file = `plugins/${name}/.claude-plugin/plugin.json`;
  const plugin = JSON.parse(fs.readFileSync(file, 'utf8'));
  plugin.version = version;
  fs.writeFileSync(file, JSON.stringify(plugin, null, 2) + '\n');
}
const marketFile = '.claude-plugin/marketplace.json';
const market = JSON.parse(fs.readFileSync(marketFile, 'utf8'));
for (const plugin of market.plugins) {
  if (versions[plugin.name]) plugin.version = versions[plugin.name];
}
fs.writeFileSync(marketFile, JSON.stringify(market, null, 2) + '\n');
JS

echo "==> Synced: dingtalk $DINGTALK_VERSION, wecomcli $WECOM_VERSION"
