# GM Command Tool

GM Command Tool 是一个运行在本机的游戏运营、测试与研发辅助工作台。它把 GM 命令、KS 环境与账号、Cocos 客户端、GM 控制台脚本、Git 仓库、配置表、协议测试和孔明助手集中到同一个 Web 界面中，帮助使用者在执行前确认目标，在执行后查看明确的结果与异常。

本项目面向经过授权的内部测试和运营场景，默认以 Windows 本机服务方式运行。它不会替代 KS、Cocos、GM 控制台或 Git，也不会自动创建 KS 环境或游戏账号。

## 功能概览

- **命令管理**：按分类搜索 GM 命令，查看说明、参数和示例，选择环境、服务器及账号后执行。
- **目标识别**：读取 KS 环境目录、历史账号和本机 Cocos 客户端状态，区分在线客户端、KS 可执行和不可执行账号。
- **账号同步**：通过 KS Token 同步当前用户有权限的环境与账号；支持浏览器桥接自动读取当前 KS 会话。
- **脚本管理**：维护 Groovy 脚本和收藏配置，选择个人环境与服务器，执行 GM 控制台自动登录和批量执行流程。
- **Git 拉取**：查看客户端和配置表仓库状态、远端提交、分支，支持拉取远端分支、切换分支、统一切换客户端与配置表，以及处理本地改动和文件占用。
- **配置表能力**：读取物品、活动等配置；支持当前配置表与前 3 个版本的差异对比，并展示变更字段和单元格差异。
- **积分计算**：根据 `COA_DramaHanZhong.xlsx` 的积分规则计算任务完成后的积分。
- **协议测试**：对本机 Cocos 客户端串行发送协议请求并收集结果。
  - 钓鱼模板显示渔场、鱼 ID、鱼名、品质、实测重量、配置重量、冠鱼重量、奖励、概率和 Wilson 置信区间。
  - 通用模板显示响应协议、响应次数、`code` 分布和响应字段摘要，不会误用 `Fish ID` 等钓鱼字段。
- **孔明助手**：基于本地客户端代码、配置表、项目文档和历史上下文进行问题分析，并支持将自然语言任务转换为可确认、可执行的任务步骤。
- **QA 测试设计**：从需求文档或上传材料生成测试点、测试用例和需求追踪结果。
- **SkillHub 集成**：查看和打开本机 AI SkillHub，支持将授权的 Skill 接入 Codex 工作目录。
- **用户与权限**：管理员负责执行、维护数据和系统配置；普通用户主要用于查询、查看、复制、计算和测试设计。

## 运行环境

- Windows 10/11
- Python 3.10 或更高版本
- Git，并且 Git 可在命令行中调用
- 可选：Chrome 或 Edge，用于 KS Token 自动同步桥接
- 可选：本机 Cocos 客户端、GM 控制台、KS 访问权限、孔明模型服务和 Codex CLI

## 快速开始

### 1. 安装依赖

```powershell
git clone https://github.com/zhb2250055704/task.git
Set-Location .\task
python -m pip install -r requirements.txt
```

当前 `requirements.txt` 只声明文档处理依赖。若启用本机已有的 Cocos、KS、GM 控制台或模型服务，还需要保证对应服务和访问权限已经配置完成。

### 2. 检查本地数据目录

默认配置使用以下目录：

```text
C:\Users\TU\Documents\client    客户端 Git 仓库
C:\Users\TU\Documents\excel     配置表 Git 仓库
```

如果本机目录不同，请在 `server.py` 的 `GIT_REPOS` 中调整 `client.path` 和 `excel.path`，同时确认配置表、客户端代码和 Git 仓库均可读取。项目不包含这些外部仓库的数据。

### 3. 启动工具

```powershell
.\Start-GMCommandTool.ps1
```

启动后打开：

```text
http://127.0.0.1:9092/login.html
```

也可以直接启动 Python 服务：

```powershell
python server.py 9092 --no-browser
```

`Start-GMCommandTool.ps1` 会检查 9092 端口上是否已经运行当前版本服务，并在代码发生变化时重新启动服务。服务健康检查地址为：

```text
http://127.0.0.1:9092/api/health
```

首次使用请按登录页提示初始化管理员账号，并在登录后立即修改密码。不要把默认密码、Token 或业务账号信息写入 README、提交记录或截图。

## KS Token 自动同步桥接

扩展源码位于 `browser-extension/ks-token-auto-sync`。

1. 在 Chrome 或 Edge 打开 `chrome://extensions/` 或 `edge://extensions/`。
2. 开启开发者模式。
3. 选择“加载已解压的扩展”。
4. 选择 `browser-extension/ks-token-auto-sync` 目录。
5. 使用同一浏览器登录 KS 和 GM Command Tool。

桥接只允许 KS 页面和本机 GM 页面参与通信。Token 不写入 URL、输入框、浏览器历史或扩展本地存储；扩展只把同步后的环境与账号结果返回给本机 GM 页面。具体排查步骤见 [浏览器桥接说明](browser-extension/ks-token-auto-sync/README.md)。

## 典型使用流程

### 执行 GM 命令

1. 登录工具并等待 KS 环境、账号和 Cocos 状态加载。
2. 在命令管理中选择分类和命令。
3. 填写命令所需参数，检查完整命令预览。
4. 选择目标环境、服务器和账号。
5. 确认执行通道和风险提示后提交。
6. 根据客户端回执、KS 投递状态或最终游戏结果判断是否完成。

工具会区分“命令已投递”和“游戏业务已成功”。网络返回成功不等于游戏逻辑一定成功，出现异常时应查看执行详情和服务日志。

### 运行协议测试

1. 进入协议测试页签。
2. 选择一个已连接且身份完整的本机 Cocos 客户端。
3. 选择钓鱼模板或通用协议模板，填写请求协议、响应协议和请求参数。
4. 先执行预检，确认目标、协议、次数和风险提示。
5. 使用隔离测试账号运行，查看实时进度和最终报告。

协议测试首期只支持单账号串行执行，单次最多 10000 次。钓鱼测试会改变道具、图鉴、重量和保底状态；通用协议测试不会根据响应中的同名字段生成钓鱼统计。

### 使用孔明助手

孔明助手可以直接回答配置、代码、协议、版本差异、GM 命令和故障排查问题，也可以识别需要执行的多步任务。涉及真实执行的任务会先生成任务计划，管理员确认后才会执行。模型服务、KS、GM 控制台和本地代码均可能受网络、权限、分支和服务状态影响，助手不会凭空补造环境或执行结果。

## 配置项

敏感配置优先通过环境变量或本机配置文件提供，不要提交到 Git。常用配置包括：

| 配置 | 用途 | 默认值 |
| --- | --- | --- |
| `GM_COCOS_WS_PORT` | Cocos WebSocket 端口 | `5101` |
| `GM_COCOS_PROXY_HTTP_PORT` | Cocos 本机代理端口 | `5200` |
| `GM_KS_TOKEN` / `GM_KS_BASE_URL` | KS 访问凭据和地址 | 空 |
| `GM_CONSOLE_USERNAME` / `GM_CONSOLE_PASSWORD` | GM 控制台默认登录信息 | 空 |
| `GM_KONGMING_MODEL_PROVIDER` | 孔明模型服务提供方 | `taishi` |
| `GM_KONGMING_MODEL` | 孔明使用的模型 | `gpt-5.5` |
| `GM_KONGMING_PROVIDER_BASE_URL` | 孔明模型服务地址 | 项目默认地址 |
| `GM_KONGMING_WORKSPACE` | 孔明检索工作区 | client 与 excel 的公共目录 |
| `GM_KONGMING_SKILLS_DIR` | 孔明 Skill 源目录 | 空 |
| `GM_SKILLHUB_DIR` / `GM_SKILLHUB_EXE` | AI SkillHub 安装目录和可执行文件 | 自动探测 |
| `GM_QA_OLLAMA_URL` / `GM_QA_OLLAMA_MODEL` | QA 本地模型地址和模型 | `http://127.0.0.1:11434` / `qwen3:14b` |
| `GM_GIT_STATUS_FETCH_TIMEOUT` | Git 远端状态检查超时 | `45` 秒 |

运行时会在 `runtime/` 中保存任务、会话、索引和报告；这些内容属于本机运行数据，已被 Git 忽略。`gm_users.json`、`gm_ks_config.json`、`gm_account_cache.json`、`gm_console_config.json` 和日志文件同样不应提交。

## 目录结构

```text
.
├─ server.py                         本地 HTTP 服务和 API 路由
├─ index.html                        登录后的主界面
├─ login.html                        登录页
├─ protocol_test.py                  协议测试服务与报告生成
├─ kongming_*.py                     孔明助手、索引、检索、任务和桥接模块
├─ qa_*.py                           QA 测试设计和文档处理模块
├─ browser-extension/                KS Token 自动同步扩展
├─ tests/                            Python 单元测试和回归测试
├─ docs/                             产品和原型相关资料
├─ stitch-export/                    Stitch 原型与设计资源
├─ PRD.md                            完整产品需求文档
├─ PRODUCT.md                        产品约束与能力边界
├─ DESIGN.md                         界面设计系统与视觉规范
├─ Start-GMCommandTool.ps1           本地服务启动脚本
└─ requirements.txt                  Python 依赖
```

## 测试与检查

运行全部测试：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

检查主要 Python 文件语法：

```powershell
python -m py_compile server.py protocol_test.py kongming_tasks.py
```

修改前端后，建议启动服务并检查：

```text
http://127.0.0.1:9092/api/health
```

高风险功能应使用隔离账号和测试环境验证，不要直接对生产账号执行 GM 命令、协议测试或会改变游戏状态的脚本。

## 安全与数据边界

- 仅在获得授权的 KS、客户端、GM 控制台和 Git 仓库上使用。
- 不要在 Issue、Pull Request、README、截图或日志中公开 Token、Cookie、密码、账号 ID、内部域名和业务数据。
- 本工具在本机处理客户端代码、配置表和运行结果；模型服务是否接收这些内容取决于本机模型配置和检索流程，部署前应按公司数据分级要求进行脱敏和审查。
- 执行高风险操作前必须确认环境、服务器、账号和命令参数；“已投递”不能替代游戏内结果验证。
- 不要将 `runtime/`、本机配置、缓存、日志和外部仓库数据强行加入版本库。

## 维护说明

产品行为和边界以 [PRD.md](PRD.md) 为准，界面规范以 [DESIGN.md](DESIGN.md) 和 `stitch-export/` 为准。修改跨模块能力时，应同步补充测试，并确认服务重启后页面和 API 仍可用。

本仓库未声明开源许可证，代码和文档的使用范围以仓库所有者及所在组织的授权为准。
