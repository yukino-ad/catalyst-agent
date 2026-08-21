# Catalyst Agent Frontend

这是全新创建的 assistant-ui 前端，不使用项目中的历史 `web/` 原型。

## Getting Started

## 当前阶段

- assistant-ui 聊天界面已经建立。
- 页面不依赖 Google Fonts 或浏览器端第三方 CDN。
- 浏览器不保存 Kimi API Key、SSH 私钥或超算配置。
- `/api/chat` 已连接 Python FastAPI，可创建真实 `task_id` 并显示 LangGraph 阶段。
- F2 强制关闭远程预检、上传和 Slurm 提交；人工门只展示并安全暂停。
- F2.1 增加本地对话入口：问候、自我介绍、功能咨询和使用帮助不会创建 `task_id`。
- 明确科研请求仍进入 FastAPI/LangGraph；短且含糊的输入会先请求补充信息。
- 所有对话文字统一采用“处理状态 -> 流式输出”节奏，包括本地说明、任务状态、人工门、结果和错误；界面不展示模型隐藏推理链。
- A1-A4 和普通 B 阶段默认只显示“阶段 + 一句话真实结果”，不额外增加等待；B6 作为人工决策门保留来源、评分和科学断言详细审查卡。
- 全局字体规则统一为：普通及浅色正文使用微软雅黑；加粗强调文字、标题和数字分点放大一级，其中英文使用 Times New Roman、中文自动回退到楷体。缺少指定字体的设备继续使用系统回退字体，后续新增回复自动继承。
- 顶部垃圾桶按钮可在确认后删除当前网页对话；运行中的回复不可删除，且该操作不会删除 `task_id`、科研结果、DFT 文件或超算作业。未来历史对话列表沿用同一删除边界。

## 本地启动

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent\frontend"
$env:Path = "C:\Program Files\nodejs;" + $env:Path
npm.cmd run dev
```

另开一个 PowerShell 启动 Python API：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
.\.venv-repro\Scripts\Activate.ps1
python -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://localhost:3000`。

## F2.1 对话入口

首页提供三个研究起点：

1. 从研究目标开始，运行正常 `A -> B -> C` 流程。
2. 直接指定五元组成，跳过文献阶段进入 direct C。
3. 使用已有 POSCAR/CIF；F4 完成前，该卡片只把示例填入输入框，不会误称已经支持上传。

以下输入由 Next.js 本地回答，不调用 Kimi、不访问 FastAPI，也不产生持久化任务：

```text
你好
请你自我介绍一下
你能做什么
请介绍一下你在高熵合金研究方面的功能
怎么使用
```

明确动作与科研对象同时出现时仍创建真实任务，例如：

```text
你好，请帮我构建 CuFeNiCoMn 五元高熵合金。
请检索用于 CO2RR 的高熵合金文献并设计五元候选。
```

入口分类位于 `lib/conversation-entry.ts`，SSE 对话转发位于 `app/api/chat/route.ts`，首页入口卡位于 `components/assistant-ui/thread.tsx`。

## 全球访问设计

- 前端和 Python API 都可部署到自己的服务器，不绑定 assistant-ui Cloud 或 Vercel。
- 所有字体和前端代码随构建产物提供，避免地区性 CDN 失败。
- Kimi、学术检索和超算 SSH 全部由 Python 服务端访问。
- 浏览器只访问自己的 HTTPS 域名，不直接连接 Kimi 或超算。
- 优先部署在香港或新加坡；若中国大陆需要长期稳定访问，再增加已备案的大陆节点。

## F3 路线图

F3 将 LangGraph 的人工中断转换为网页可操作的审查门，并通过统一 API 恢复原 `task_id`。实施顺序如下：

1. 定义统一审查契约、允许的操作和安全展示字段。
2. 增加审查提交 API、服务端校验、幂等控制和审计记录。
3. 实现文献 B6、候选 C4 与 C 阶段执行范围选择。
4. 实现 slab、吸附结构、VASP 输入和吸附能审查。
5. 最后实现上传与 Slurm 提交的高风险确认；在此之前继续强制关闭远程写入和提交。
6. 增加任务刷新、恢复、错误反馈和回归测试。

F3 完成后再实现“领域新手 / 领域熟悉者”模式，以复用同一套交互组件：

- 首次说明结束后让用户选择理解模式，并允许之后切换。
- 新手模式逐步解释正在做什么、为什么做、输出含义和下一步，并提供“我已明白，继续进行任务”。
- 熟悉者模式只显示关键参数、状态、结果和风险。
- 模式仅改变说明详细程度，不改变 ABC 图、科学判据、人工审批结果或超算安全门。

### 当前 F3 完成范围

第一版 F3 已完成四类低风险网页人工门：

- B6 文献及科学断言接受、拒绝和暂缓。
- C4 候选选择、拒绝和暂缓，且执行最多三项限制。
- C 阶段范围单选：仅候选、FCC、稳定性预筛或 DFT 验证。
- C7 通过结构进入 C8/DFT 的选择、拒绝和暂缓。

用户点击“提交并继续任务”后，Next.js 同域 API 将决定转发到 FastAPI；服务端核对 `task_id`、`review_id`、类型、对象 ID、互斥决定和数量限制，再通过 `Command(resume=...)` 恢复原 LangGraph checkpoint。审查卡持续轮询同一任务，并自动显示下一人工门或终态。重复请求由幂等键保护。

远程上传、`sbatch`、结果下载及受控重算暂未开放网页按钮，服务端继续强制关闭远程写入和提交。后续 F3 扩展将复用当前审查契约，但必须经过独立的确认短语、摘要和副作用测试。

## 关键文件

You can start customizing the UI by modifying components in the `components/assistant-ui/` directory.

To add more assistant-ui components:

```bash
npx assistant-ui add
```

### Key Files

- `app/assistant.tsx`：assistant-ui Runtime 和页面框架。
- `app/api/chat/route.ts`：本地会话分流和 FastAPI 服务端转发入口。
- `lib/conversation-entry.ts`：问候、帮助、含糊输入和科研任务分类。
- `components/assistant-ui/thread.tsx`：消息、输入框和附件控件。
- `app/layout.tsx`：页面元数据和本地系统字体。
