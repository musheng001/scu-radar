# GPT 进展录入：一次性配置

## 1. 准备 API 密钥

使用 OpenAI API 密钥，不要把密钥发到聊天、写进网页、JavaScript 或项目文件。ChatGPT 订阅与 API 账单彼此独立。

## 2. 保存到 Windows 用户环境变量

1. 在开始菜单搜索“编辑账户的环境变量”。
2. 新建用户变量 `OPENAI_API_KEY`，值填你的 API 密钥。
3. 可选：新建 `OPENAI_MODEL`，值填 `gpt-5-mini`；不设置也会使用该默认值。
4. 关闭已经打开的终端窗口，让新环境变量生效。

## 3. 启动

双击 `启动川大雷达.cmd`。浏览器会打开 `http://127.0.0.1:8767/index.html`。点击“GPT 录入进展”，输入自然语言，先核对 GPT 整理出的草稿，再点击“确认写入”。

数据只保存到本机的 `progress-log.json`；保存后会同步重建 `secretary-brief.html`。本地服务默认只监听 `127.0.0.1`，不会向局域网开放。
