from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGETS = (
    (".venv", "duplicate_environment", "可重建；确认只使用 .venv-repro 后可人工删除"),
    (".venv-repro", "active_environment", "当前推荐环境，保留"),
    ("models/cgcnn-master/venv", "migration_required", "当前仍通过 PYTHONPATH 间接使用；先迁移到 .venv-repro 再删除"),
    ("frontend/node_modules", "regenerable", "可由 npm ci 重建"),
    ("frontend/.next", "regenerable", "可由 npm run build 重建"),
    ("data/edge-qa-selection", "regenerable", "浏览器 QA 临时用户目录"),
    ("tmp", "regenerable", "临时日志与缓存"),
    ("web", "legacy_prototype", "已被 frontend/ 替代；人工确认无引用后可归档"),
    ("app/legacy", "legacy_prototype", "旧 GUI/Web 仅内部互引；现代主图未调用，体积很小"),
    ("archive", "manual_review", "旧备份；逐项确认后再移出项目"),
    ("data/checkpoints", "runtime_state", "LangGraph 恢复历史；备份和筛选后再处理"),
    ("data/checkpoints/catalyst_graph.sqlite", "runtime_state", "主要恢复数据库；停止后端并备份后才能压缩"),
    ("data/workflow_runs", "runtime_state", "任务历史与恢复记录，保留"),
    ("data/cluster_jobs", "runtime_state", "超算作业记录，保留"),
    ("data/cluster_results", "scientific_result", "下载的 DFT 结果，保留"),
    ("database/PBE", "licensed_scientific_asset", "VASP PAW 数据，不删除且不得公开"),
    ("database/literature", "scientific_asset", "本地文献数据库，保留"),
    ("models/cgcnn-master/pre-trained", "scientific_asset", "形成能预训练模型，保留"),
    ("models/formation-energy-cgcnn", "scientific_asset", "形成能模型与配置，保留"),
)


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def audit(root: Path) -> list[dict[str, object]]:
    rows = []
    for relative, category, recommendation in TARGETS:
        path = root / relative
        size = directory_size(path)
        rows.append({
            "path": relative,
            "exists": path.exists(),
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 1),
            "category": category,
            "recommendation": recommendation,
        })
    return sorted(rows, key=lambda row: int(row["size_bytes"]), reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only Catalyst Agent storage audit. This command never deletes files."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()
    rows = audit(PROJECT_ROOT)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print("Catalyst Agent storage audit (read-only)\n")
    for row in rows:
        print(
            f"{row['size_mb']:>9.1f} MB  {row['category']:<26} "
            f"{row['path']}\n             {row['recommendation']}"
        )


if __name__ == "__main__":
    main()
