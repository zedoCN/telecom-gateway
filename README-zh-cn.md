# 电信网关 CLI

简体中文 | [English](README.md)

`ctgw` 是一个面向部分中国电信家庭网关的实验性开源命令行客户端。它用一个轻量 Go 二进制和可复用 Go 包，替代原先已经分叉的 Java/Kotlin API 与浏览器管理器。

目前只针对 **TEWA-1000E**、固件 **Tianyi_V1.0_JS2011** 上实际观测到的 LuCI 风格 CGI 接口开发。其它型号或固件可能具有不同的登录流程、字段和写入行为；新增兼容声明必须同时提供脱敏测试样本和真实硬件验证。

## 功能

- 查询网关状态、WAN/LAN 信息、在线设备和端口映射。
- 精确新增、启用、禁用或删除一条端口映射。
- 请求重启网关。
- 支持易读表格和结构化 JSON 输出。
- `info` 默认隐藏 MAC、序列号、SSID 和宽带账号。
- 所有修改命令都强制要求 `--yes`。
- 拒绝同名隐式覆盖，并通过重新读取列表验证端口映射写入结果。
- 运行时只依赖 Go 标准库。
- 内置 Agent 开发说明和可复用的 `ctgw` 操作 Skill。

项目明确不提供 Web UI，也不提供后台 daemon。

## 安装

从源码构建需要 Go 1.22 或更高版本。

```bash
go install github.com/zedoCN/telecom-gateway/cmd/ctgw@latest
```

从仓库构建：

```bash
make build
./bin/ctgw version
```

GitHub 仓库和首个 Release 建立前，请先使用本地构建命令。

## 身份验证

全局参数必须放在子命令前。默认网关地址为 `http://192.168.1.1`。

```bash
ctgw --username useradmin --password-stdin status
```

通过标准输入输入密码。无人值守运行也支持 `CTGW_URL`、`CTGW_USERNAME` 和 `CTGW_PASSWORD`。

不要把密码直接写进命令参数、仓库文件、Issue、CI 日志或 shell 历史。

## 使用方式

先执行只读命令：

```bash
ctgw --username useradmin --password-stdin status
ctgw --username useradmin --password-stdin info
ctgw --username useradmin --password-stdin devices
ctgw --username useradmin --password-stdin port list
```

在子命令前加入 `--json` 可获得机器可读输出：

```bash
ctgw --json --username useradmin --password-stdin port list
```

只有明确需要时才显示敏感网关标识：

```bash
ctgw --username useradmin --password-stdin info --show-sensitive
```

CLI 会在修改前后自动读取端口映射、拒绝同名隐式覆盖并验证回读结果。所有写操作都要求 `--yes`：

```bash
ctgw port add \
  --name example-game \
  --client 192.0.2.10 \
  --protocol UDP \
  --external-port 8211 \
  --internal-port 8211 \
  --yes

ctgw port disable --name example-game --yes
ctgw port enable --name example-game --yes
ctgw port delete --name example-game --yes
ctgw reboot --yes
```

示例使用文档专用地址；请通过全局参数或环境变量提供登录信息。运行 `ctgw help` 查看完整命令面。

## Agent 使用

本仓库将 Agent 开发作为正式入口：

- [`AGENTS.md`](AGENTS.md) 定义仓库边界和验证规则。
- [`.agents/skills/develop-telecom-gateway/SKILL.md`](.agents/skills/develop-telecom-gateway/SKILL.md) 指导开发和维护。
- [`.agents/skills/use-ctgw/SKILL.md`](.agents/skills/use-ctgw/SKILL.md) 指导 Agent 安全调用 CLI。

如需在个人 Codex 中使用操作 Skill，将整个 `use-ctgw` 目录复制到 `${CODEX_HOME:-$HOME/.codex}/skills/`，然后调用 `$use-ctgw`。

## 开发

```bash
make check
```

测试只使用 `httptest` 和虚构的文档地址。禁止把真实凭据、Cookie、Token、完整网关响应、宽带账号、MAC、序列号或 SSID 放进测试样本。

提交改动前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。

## 许可证

[MIT](LICENSE)
