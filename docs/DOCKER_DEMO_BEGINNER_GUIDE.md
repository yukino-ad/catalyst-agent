# Docker Demonstration Guide

This guide is for running the Catalyst Agent on another Windows computer.
The other computer does not need Python, Node.js, VASP, or the project virtual
environment. It only needs Docker Desktop and a Kimi K3 API key.

## 1. What you must do

1. Install Docker Desktop and start it.
2. Copy this package to the other computer, for example to:
   `D:\catalyst-agent-demo`.
3. Open PowerShell in that directory.
4. Create the private environment file:

```powershell
Copy-Item ".env.demo.example" ".env"
notepad ".env"
```

Replace `replace-with-your-kimi-k3-api-key` with your own Kimi K3 API key.
Do not upload `.env` to GitHub or send it to other people.

## 2. Start the site

```powershell
Set-Location "D:\catalyst-agent-demo"
powershell -ExecutionPolicy Bypass -File ".\scripts\start_demo.ps1"
```

Open this address in a browser:

```text
http://127.0.0.1:3000
```

The first start can take several minutes because Docker builds the two images.

## 3. Stop the site

```powershell
Set-Location "D:\catalyst-agent-demo"
powershell -ExecutionPolicy Bypass -File ".\scripts\stop_demo.ps1"
```

Stopping containers does not delete the task data.

## 4. Useful diagnostics

```powershell
docker compose -f docker-compose.demo.yml ps
docker compose -f docker-compose.demo.yml logs backend
docker compose -f docker-compose.demo.yml logs frontend
Invoke-RestMethod "http://127.0.0.1:8000/api/health" | ConvertTo-Json -Depth 5
```

If port 3000 or 8000 is already in use, stop the existing program or change
the left side of the corresponding port mapping in `docker-compose.demo.yml`.

## 5. Demonstration task

The included completed task is:

```text
external-c-dft-20260725-145226
```

It contains clean-slab relaxation, CO adsorption DFT input and result data,
and the reviewed adsorption-energy record. Select it from the task history.

## 6. Safety boundary

The demo compose file forces these settings to false:

```text
WEB_REMOTE_OPERATIONS_ENABLED=false
CLUSTER_PREFLIGHT_ENABLED=false
CLUSTER_REMOTE_WRITE_ENABLED=false
CLUSTER_SUBMISSION_ENABLED=false
```

This package cannot upload to a cluster or submit a Slurm job. Use the separate
administrator deployment configuration for real remote computation.
