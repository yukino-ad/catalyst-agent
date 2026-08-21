# Catalyst Agent Full Package

This package contains the complete application source, frontend, backend,
LangGraph workflow, local literature and formation-energy data, CGCNN model
weights, task history, structures, and saved DFT results.

It can run the full local Agent workflow. Real remote DFT upload and Slurm
submission additionally require the deployment owner to provide Kimi
credentials, cluster SSH credentials, and licensed VASP/POTCAR resources.

Start the local full package with:

```powershell
Copy-Item .env.full.example .env
notepad .env
powershell -ExecutionPolicy Bypass -File .\scripts\start_full.ps1
```

Open `http://127.0.0.1:3000`.
See `docs/DOCKER_FULL_BEGINNER_GUIDE.md` for the complete setup.
