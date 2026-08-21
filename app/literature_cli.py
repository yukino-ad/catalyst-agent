from __future__ import annotations

import argparse
import json

from tools.literature.extractor import LiteratureExtractor
from tools.literature.openalex_client import OpenAlexClient
from tools.literature.repository import LiteratureRepository
from tools.literature.schemas import Assertion, Evidence, PaperRecord


def import_samples(repository: LiteratureRepository) -> int:
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "data/papers/sample_papers.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    for index, value in enumerate(values, 1):
        assertions = []
        if value.get("elements"):
            assertions.append(Assertion("element_set", value["elements"], "explicit", "medium", [], False))
        if value.get("adsorbates"):
            assertions.append(Assertion("intermediate", value["adsorbates"], "explicit", "medium", [], False))
        repository.upsert(PaperRecord(
            paper_id=f"sample:{index}", title=value["title"], year=value.get("year"), source="sample",
            summary=" ".join(value.get("insights", [])), assertions=assertions,
        ))
    return len(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="管理 Catalyst Agent 文献数据库")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="初始化 SQLite 数据库")
    subparsers.add_parser("import-samples", help="导入离线示例文献")
    fetch = subparsers.add_parser("fetch", help="从 OpenAlex 搜索并入库")
    fetch.add_argument("query")
    fetch.add_argument("--count", type=int, default=10)
    fetch.add_argument("--extract", action="store_true", help="用 LLM 抽取后再入库")
    search = subparsers.add_parser("search", help="检索本地文献库")
    search.add_argument("query")
    search.add_argument("--reaction", default="")
    search.add_argument("--product", default="")
    search.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    repository = LiteratureRepository()
    if args.command == "init":
        print(f"数据库已初始化：{repository.db_path}")
    elif args.command == "import-samples":
        print(f"已导入 {import_samples(repository)} 条示例记录；当前共 {repository.count()} 条。")
    elif args.command == "fetch":
        papers = OpenAlexClient().search(args.query, per_page=args.count)
        extractor = LiteratureExtractor() if args.extract else None
        for paper in papers:
            repository.upsert(extractor.extract(paper) if extractor else paper)
        print(f"已保存 {len(papers)} 条 OpenAlex 记录；当前共 {repository.count()} 条。")
    elif args.command == "search":
        filters = {key: value for key, value in {"reaction": args.reaction, "product": args.product}.items() if value}
        print(json.dumps(repository.search(args.query, filters, args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
