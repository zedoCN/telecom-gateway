# Telecom Gateway

[English](README.md)

`ctgw` 是 Python 命令行工具和可独立安装的 Agent Skill，用于授权管理**电信 TEWA-1000E、固件 Tianyi_V1.0_JS2011**。网页相似不代表兼容其他设备；不支持 TP-Link SAR205GP-CM。

`main` 为 Python + Agent Skill；原 Go CLI/库完整保留在 [`go` 分支](https://github.com/zedoCN/telecom-gateway/tree/go)，起点提交 `e5058897d24e8d335c84248ff57e5022a0bc2deb`。Go 用户可运行 `go install github.com/zedoCN/telecom-gateway/cmd/ctgw@go`；主分支不再提供 Go 库。

## 安装

需要 Python 3.10+。用 [uv](https://docs.astral.sh/uv/) 安装 CLI，或在虚拟环境中使用 pip：

```sh
uv tool install 'git+https://github.com/zedoCN/telecom-gateway.git@main'
ctgw help
ctgw --json doctor
```

在源码目录运行 `python -m pip install .` 也可安装，不依赖 PyPI 发布。

### Agent Skill

用支持 GitHub 的 Skill 安装器安装整个 `.agents/skills/use-ctgw` 目录，或在源码目录执行：

```sh
python scripts/skill_bundle.py install
# Codex 另一种 Skill 根目录：
python scripts/skill_bundle.py install --destination ~/.codex/skills
python scripts/skill_bundle.py pack --output dist/use-ctgw.zip
```

默认安装到 `~/.agents/skills/use-ctgw`。已有文件、目录或符号链接会被拒绝覆盖；更新应通过原安装的归属仓库处理。ZIP 附 SHA-256 校验文件，包含 Skill、Python 源码、命令参考和 MIT 许可，无需 Go、按架构编译的二进制或修改 PATH。

安装后可脱离源码仓库运行：

```sh
uv run /absolute/path/use-ctgw/scripts/ctgw.py --json doctor
```

`uv` 自动读取脚本依赖；已有 Python 和 `keyring` 时，也可用 `python /absolute/path/use-ctgw/scripts/ctgw.py ...`。help/version/doctor 和完全通过环境提供凭据的调用无需加载系统凭据库。ZIP 不包含 Python 解释器和依赖 wheel，首次准备依赖可能需要联网。

## 凭据

全局参数放在命令之前：

```text
ctgw [--url URL] [--username NAME] [--password-stdin] [--json] [--timeout 15s] COMMAND
ctgw --username NAME --password-stdin auth login
ctgw auth status
ctgw auth logout
```

密码通过已有安全 stdin 来源或进程环境输入，不写入命令参数、聊天或公开日志。`auth login` 先验证登录再保存；`auth status/logout` 仅操作本地凭据，不访问网关。URL/用户名按参数、`CTGW_URL`/`CTGW_USERNAME`、已保存配置的顺序取值；密码按 stdin、`CTGW_PASSWORD`、相同 URL 和用户名对应的凭据库记录取值。默认 URL 是 `http://192.168.1.1`。

密码保存在 macOS 钥匙串、Windows 凭据管理器或 Linux Secret Service；Linux 需要可用的 login collection 和 D-Bus 会话，无明文降级。无桌面机器可使用进程凭据。配置只保存 URL 和用户名：

- macOS：`~/Library/Application Support/ctgw/profile.json`
- Windows：`%APPDATA%/ctgw/profile.json`
- Linux：`$XDG_CONFIG_HOME/ctgw/profile.json`，否则 `~/.config/ctgw/profile.json`

POSIX 配置目录/文件权限为 0700/0600，Windows 使用当前用户继承的 ACL。Go 版 macOS 编码及 Linux 属性兼容已做模拟测试，尚未逐平台实测迁移。**从 Go 迁移的 Windows 用户需重新 `auth login`**；Python 的 `auth logout` 不删除旧 Go Windows 凭据。

## 查询与修改

```sh
ctgw --json status
ctgw --json info
ctgw --json devices
ctgw --json port list
ctgw --json port add --name demo --client 192.0.2.10 --protocol TCP --external-port 8443 --internal-port 443 --yes
ctgw --json port disable --name demo --yes
ctgw --json port enable --name demo --yes
ctgw --json port delete --name demo --yes
ctgw --json reboot --yes
```

修改前先查询并保留恢复入口。所有网关写操作必须带 `--yes`。端口映射只处理一个精确名称，拒绝重复名称、不完整列表及隐式替换；修改后读回目标并检查其他规则未变。已处于目标启停状态时直接成功，不再提交。没有批量操作、自动重试或自动回滚。写入超时或读回失败时，先查询实际状态再决定是否重试。重启成功输出只表示请求已提交，恢复需另外检查设备状态及互联网连通性。

`info` 在文本和 JSON 中默认隐藏 MAC、序列号、SSID、WAN 账号；`info --show-sensitive` 才在本地显示已知敏感字段。设备列表与映射仍可能包含内网信息，分享时精简。

查询 JSON 保留 Go 字段名，新增诊断、凭据和写操作 JSON，例如 `{"action":"port disable","name":"demo","changed":true,"verified":true}`、`{"action":"reboot","requested":true}`。错误写入 stderr，不附原始网关响应。退出码：0 成功，1 操作失败或结果不确定，2 用法或缺少凭据，130 中断。文本排版可与 Go 不同。

`--timeout` 支持秒数和 `250ms`、`15s`、`1m30s`，限制整条命令的 socket I/O；系统 DNS 解析可能超过此预算。响应有大小限制，拒绝跟随跳转。代理遵循 Python 标准 URL opener 的环境变量行为，内网目标按需配置 `NO_PROXY`。HTTP 管理页面不加密凭据，应使用可信网络或安全隧道。

## 开发与验证范围

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/skill_bundle.py pack
python -m pip install build
python -m build
```

协议和 CLI 测试使用 localhost 模拟网关，凭据测试注入假存储；普通测试不访问真实设备或系统钥匙串。CI 覆盖 Linux/macOS/Windows 的 Python 3.10/3.13，构建 wheel、源码包和 Skill ZIP；不代表原生凭据库和真实设备写操作验收。Python 迁移尚未新增实机验收；原 Go 版在上述型号/固件做过只读验证。

参见 [贡献说明](CONTRIBUTING.md)、[安全政策](SECURITY.md) 和 [MIT 许可](LICENSE)。
