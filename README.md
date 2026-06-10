# Xshell Session 文件自动生成器

从 CSV 服务器清单批量生成 Xshell session 文件（`.xsh`），以及批量修改已保存的密码。

## 环境要求

- Python 3.10+
- 零第三方依赖（仅使用标准库）

## 功能一：批量生成 session 文件

### 1. 准备模板

从 Xshell 导出一个已配置好的 session 文件作为模板，用文本编辑器打开，将设备 IP 替换为 `{{HOST}}`：

**直接登录模式**（SSH/Telnet 直连）：
```ini
[CONNECTION]
Host={{HOST}}
```

**堡垒机登录模式**（Expect/Send 跳转）：
```ini
[CONNECTION]
Host=10.0.0.1               # 堡垒机地址保持不变

[CONNECTION:AUTHENTICATION]
UseExpectSend=1
; 在 Send 规则中将设备 IP 替换为占位符
SendX=ssh {{HOST}}
```

> 其他配置（密码、终端配色、字体、SSH 参数等）完全保留，无需修改。

### 2. 准备 CSV

| 列名 | 必填 | 说明 |
|------|------|------|
| SessionName | ✅ | 生成的 .xsh 文件名（不含扩展名） |
| Host | ✅ | 设备管理 IP |
| Group | ❌ | 分组文件夹，`/` 分隔层级。如 `北京四/az1/fa` |

示例 `servers.csv`：
```csv
SessionName,Host,Group
web-01-10.1.1.1,10.1.1.1,北京四/az1/fa
web-02-10.1.1.2,10.1.1.2,北京四/az1/fa
```

### 3. 运行

```bash
# 基本用法
python xshell_gen.py generate 模板.xsh 服务器.csv

# 预览（不写入文件）
python xshell_gen.py generate 模板.xsh 服务器.csv --dry-run

# 指定输出目录
python xshell_gen.py generate 模板.xsh 服务器.csv -o "D:\Sessions"

# 平铺输出（不创建分组文件夹）
python xshell_gen.py generate 模板.xsh 服务器.csv --flat

# 覆盖已存在文件
python xshell_gen.py generate 模板.xsh 服务器.csv --force
```

输出目录默认自动检测 Xshell Sessions 目录（按版本 5/6/7/8 依次探测）。

---

## 功能二：批量修改密码

### 使用场景

定期更换堡垒机密钥密码或设备登录密码时，只需在 Xshell 中手动修改**一个** session 的密码，然后用工具批量同步到其他 session。

### 使用流程

1. 在 Xshell 中修改一个 session 的密码/密钥密码并保存
2. 运行工具：

```bash
# 交互式选择目标文件夹
python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh

# 命令行直接指定目标（跳过交互）
python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh -t 1,3-5
python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh -t all

# 预览（不实际修改）
python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh --dry-run
```

参数说明：
| 参数 | 说明 |
|------|------|
| `source` | 源 session 相对路径（相对于 Sessions 目录） |
| `-t` | 目标文件夹序号，如 `1`、`1-3`、`1,3-5`、`all`。不填则交互式选择 |
| `--field` | 要更新的字段：`passphrase`（默认）、`password`、`all` |
| `--dry-run` | 预览变更，不实际修改 |

### 交互式选择示例

```
Sessions 目录: C:\Users\admin\Documents\NetSarang Computer\7\Xshell\Sessions
源 session: C:\Users\admin\...\Sessions\北京四\az1\fa\sw01.xsh
已提取 Passphrase: Jd8kL2****

第一层文件夹：
  [1] 北京四              (12 个 session)
  [2] 上海                (8 个 session)
  [3] 广州                (5 个 session)
  [a] 全部

请选择目标文件夹（如: 1 / 1-3 / 1,3,5 / a）：
```

---

## 工作原理

- `.xsh` 文件是 INI 格式文本，密码存储在 `[CONNECTION:AUTHENTICATION]` section 的 `Password=` 和 `Passphrase=` 字段中
- Xshell 使用专有加密算法保护这些字段
- 工具不做加解密——只是从源 session **复制加密值**到目标 session，Xshell 可以正常解密
- 这保证了密码安全：工具不需要知道明文密码

## 列名兼容

CSV 列名支持中英文（大小写不敏感）：

| 标准名 | 支持的列名 |
|--------|-----------|
| SessionName | sessionname, 会话名, 名称, 设备名, name |
| Host | host, ip, 管理ip, 地址, ip地址, hostip, 设备ip |
| Group | group, 分组, 目录, folder |
