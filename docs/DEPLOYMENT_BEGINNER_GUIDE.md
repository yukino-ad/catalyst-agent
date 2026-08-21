# Catalyst Agent 部署与 Git/GitHub 小白指南

## 1. 先理解四个部分

- **源码**：`app/`、`tools/`、`frontend/` 等目录中的程序。
- **Git**：本机的版本历史工具，相当于给代码建立可命名、可回退的存档点。
- **GitHub**：互联网上保存 Git 仓库、展示 README、协作和发布代码的平台。它不会自动运行 Agent。
- **Docker**：把 Python、Node.js、依赖和启动方式打包成可复现的运行环境。

推荐展示链路：

```text
浏览器 -> Next.js 前端 -> FastAPI 后端 -> Kimi / 学术 API / HPC SSH
```

GitHub 负责保存代码，Docker 负责运行代码，云服务器负责让其他国家和地区的浏览器访问。

## 2. 本机 Docker 安全演示

安装 Docker Desktop 并启动后，在 PowerShell 执行：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
docker compose build
docker compose up -d
docker compose ps
```

浏览器打开 `http://127.0.0.1:3000`。查看日志：

```powershell
docker compose logs -f backend
docker compose logs -f frontend
```

停止但保留数据：

```powershell
docker compose down
```

默认 `docker-compose.yml` 强制关闭网页上传和 Slurm 提交，适合公开展示界面与本地流程。

## 3. 本机 Docker 连接真实 Kimi 和超算

1. 在 `.env` 中填写真实 Kimi、SSH、Slurm 配置。
2. 不要把 `.env`、SSH 私钥和 `database/PBE` 上传到 GitHub 或打入镜像；HPC 配置会在运行时只读挂载 PBE 目录。
3. 额外填写 Docker 主机路径：

```dotenv
CLUSTER_SSH_KEY_HOST_PATH=C:/Users/chenheli/.ssh/scnet_hpccube
CLUSTER_KNOWN_HOSTS_HOST_PATH=C:/Users/chenheli/.ssh/known_hosts
VASP_PBE_HOST_PATH=C:/Users/chenheli/Documents/agent开发/catalyst-agent/database/PBE
```

用两份 Compose 配置叠加启动：

```powershell
docker compose -f docker-compose.yml -f docker-compose.hpc.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.hpc.yml ps
```

此模式仍不会绕过人工门：

1. C10 逐文件确认。
2. C11 选择计算方式。
3. 输入 `UPLOAD <task_id>` 才允许上传。
4. 远程 SHA-256 一致后，输入 `SUBMIT <task_id>` 才允许 `sbatch`。

工作台标题旁的状态栏会做一次真实检查：Kimi 用最小对话请求；超算只用 SSH 回显，不创建目录、不提交作业。可点刷新按钮重新检查。

## 4. 部署到公网

适合初学者的方案是一台香港、新加坡或其他可同时访问 Kimi 与超算登录节点的 Linux 云服务器：

1. 购买带公网 IP 的 Ubuntu 服务器，建议至少 4 核、16 GB 内存、80 GB 磁盘。科学依赖和 PyTorch 使后端镜像较大。
2. 安装 Docker Engine 和 Compose 插件。
3. 用私有 GitHub 仓库拉取代码，或上传不含敏感文件的发布压缩包。
4. 在服务器单独创建 `.env` 和只读 SSH 密钥文件。
5. 执行 `docker compose up -d --build`。
6. 用 Nginx/Caddy 将域名的 HTTPS 请求转发到前端 `3000` 端口。

全球访问取决于云服务器区域、域名和网络线路，不取决于前端框架。公开站点必须增加登录、速率限制和操作员权限；否则陌生访客可能消耗 Kimi 额度或尝试提交超算作业。推荐做法：

- 普通访客只能查看演示任务、报告和三维结构。
- 登录的研究用户可以创建本地任务和咨询 Kimi。
- 只有管理员可看到真实上传与提交确认卡。

Vercel 只适合单独托管前端，不适合这个完整后端，因为后端需要持久化文件、科学依赖和 SSH。单台 Linux VPS + Docker Compose 更容易复现。

## 5. Git 和 GitHub 入门

首次初始化本地仓库：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
git init
git branch -M main
git status
git add .
git status
git commit -m "Initial Catalyst Agent release"
```

先在 GitHub 网页创建一个**私有空仓库**，不要勾选自动 README。然后执行：

```powershell
git remote add origin https://github.com/<你的用户名>/catalyst-agent.git
git push -u origin main
```

以后每次保存一个版本：

```powershell
git status
git add .
git commit -m "Describe this change"
git push
```

提交前必须确认 `git status` 中没有：`.env`、私钥、POTCAR、checkpoint、DFT 敏感结果、虚拟环境、`node_modules` 或 `.next`。GitHub 对大文件有限制，训练模型若确实需要发布，应先确认许可证，再考虑 Git LFS 或独立 Release。

## 6. 远程 API

后端启动后，接口说明位于 `http://<服务器>:8000/docs`。前端通过服务器端代理访问 FastAPI，容器内地址由下列变量配置：

```dotenv
CATALYST_API_BASE_URL=http://backend:8000
```

不要直接把未鉴权的 FastAPI `8000` 端口暴露到公网。公网只开放 HTTPS 前端入口，由反向代理和认证层控制访问。

## 7. 存储空间与发布包

只读审计：

```powershell
.\.venv-repro\Scripts\python.exe scripts\storage_audit.py
```

该命令不会删除任何文件。通常可重建的是 `.venv`、`models/cgcnn-master/venv`、`frontend/.next`、`frontend/node_modules` 和浏览器 QA 缓存；`data/checkpoints` 是恢复历史，必须先备份和筛选，不能直接删除。
