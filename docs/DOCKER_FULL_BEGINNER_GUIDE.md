# Full Agent Docker Deployment Guide

## What this package provides

After Docker deployment, the computer can run the complete local Agent:

- natural-language task entry and routing;
- A1-A4 task analysis;
- B1-B6 local literature retrieval, scoring, and review;
- C-stage candidate design, structure generation, CGCNN prediction, and stability screening;
- slab and adsorption structure preparation;
- saved task history, recovery, reports, file previews, and structure views;
- existing DFT result and adsorption-energy demonstrations;
- Kimi K3 consultation and workflow explanations.

## What cannot be copied inside the image

These must be provided by the deployment owner:

- `LLM_API_KEY`;
- cluster SSH private key and `known_hosts`;
- licensed VASP/POTCAR/PBE data;
- any institution-specific cluster permission or source-IP allowlist.

They are deliberately excluded from the package.

## 1. Install Docker Desktop

On the target Windows computer, install Docker Desktop and start it.
Open PowerShell and confirm:

```powershell
docker --version
docker compose version
```

## 2. Copy the package

Copy the entire `catalyst-agent-full` folder to the target computer, for example:

```text
D:\catalyst-agent-full
```

Do not copy only `frontend` or only `app`; the complete folder is required.

## 3. Configure Kimi

```powershell
Set-Location "D:\catalyst-agent-full"
Copy-Item ".env.full.example" ".env"
notepad ".env"
```

Set at least:

```dotenv
LLM_ENABLED=true
LLM_API_KEY=your-real-kimi-k3-key
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=kimi-k3
```

Keep these false for local-only operation:

```dotenv
WEB_REMOTE_OPERATIONS_ENABLED=false
CLUSTER_PREFLIGHT_ENABLED=false
CLUSTER_REMOTE_WRITE_ENABLED=false
CLUSTER_SUBMISSION_ENABLED=false
```

## 4. Start the full local Agent

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\start_full.ps1"
```

Open:

```text
http://127.0.0.1:3000
```

The first build may take several minutes because Docker installs Python and
Node dependencies and builds the Next.js frontend.

## 5. Enable real remote DFT only on an authorized computer

The target computer must have valid SSH access to the cluster and the cluster
must allow its network address. Place the private key and `known_hosts` on the
target computer, then edit `.env`:

```dotenv
WEB_REMOTE_OPERATIONS_ENABLED=true
CLUSTER_PREFLIGHT_ENABLED=true
CLUSTER_REMOTE_WRITE_ENABLED=true
CLUSTER_SUBMISSION_ENABLED=true
CLUSTER_SSH_HOST=your-cluster-login-host
CLUSTER_SSH_PORT=65082
CLUSTER_SSH_USER=your-cluster-user
CLUSTER_SSH_KEY_HOST_PATH=C:/Users/your-name/.ssh/cluster_key
CLUSTER_KNOWN_HOSTS_HOST_PATH=C:/Users/your-name/.ssh/known_hosts
VASP_PBE_HOST_PATH=C:/path/to/licensed/VASP/PBE
```

First run only the read-only preflight:

```powershell
docker compose -f docker-compose.full.yml -f docker-compose.hpc.yml run --rm backend python -m app.cluster_jobs_cli preflight
```

Then start with the HPC overlay:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\start_full.ps1" -WithHpc
```

The upload and Slurm submission confirmation gates remain required.

## 6. Useful commands

```powershell
docker compose -f docker-compose.full.yml ps
docker compose -f docker-compose.full.yml logs -f backend
docker compose -f docker-compose.full.yml logs -f frontend
Invoke-RestMethod "http://127.0.0.1:8000/api/health" | ConvertTo-Json -Depth 6
powershell -ExecutionPolicy Bypass -File ".\scripts\stop_full.ps1"
```

## 7. Important distinction

The Docker package reproduces the Agent software and local scientific data.
It does not transfer institutional access to Kimi, the supercomputer, VASP,
or licensed pseudopotentials. Full remote computation is therefore available
only after the deployment owner supplies those external resources.
