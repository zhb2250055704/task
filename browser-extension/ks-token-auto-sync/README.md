# KS Token 自动同步桥接

该扩展只在以下页面运行：

- `https://zxty.tuyoo.com/keystone/*`
- `http://localhost:9092/*`
- `http://127.0.0.1:9092/*`

## 首次安装

1. 在 Chrome 或 Edge 地址栏打开 `chrome://extensions/` 或 `edge://extensions/`。
2. 打开“开发者模式”。
3. 点击“加载已解压的扩展”。
4. 选择当前 `ks-token-auto-sync` 目录。
5. 使用同一个浏览器登录 KS 与 GM 命令管理工具。

安装完成后，每次登录 GM 工具都会在后台打开 KS Token 页面，读取当前浏览器的 `localStorage.TOKEN`，关闭后台页，然后自动同步个人环境和账号。

Token 不会写入浏览器历史、URL、网页输入框或扩展本地存储，也不会发送到 GM 本机服务之外的地址。扩展只把同步后的环境与账号结果返回给 GM 页面。
