from __future__ import annotations

import json

from app.planner import TaskPlanner
from app.task_router import TaskRouter
from tools.llm_client import LLMError, OpenAICompatibleClient
from tools.literature_rag import LiteratureRAG


def main() -> None:
    client = OpenAICompatibleClient()
    settings = client.settings
    print("LLM configuration")
    print(f"- enabled: {settings.enabled}")
    print(f"- base_url: {settings.base_url}")
    print(f"- model: {settings.model or '(not set)'}")
    print(f"- api_key: {'configured' if settings.api_key else 'not set'}")
    if not client.available:
        print("\nConfiguration is incomplete. Copy .env.example to .env and fill in the values.")
        return

    try:
        settings.validate()
    except LLMError as error:
        print(f"\nLLM configuration error: {error}")
        return

    question = "设计用于 CO2 还原生成 CO 的高熵催化剂"
    try:
        planner = TaskPlanner(client)
        route = TaskRouter(client).route(question)
        plan = planner.plan(question)
        rag = LiteratureRAG(llm=client).run(
            route.get("rag_query") or question, plan, top_k=3
        ) if route["use_rag"] else None
    except LLMError as error:
        print(f"\nLLM request failed: {error}")
        return
    print("\nRouter result")
    print(json.dumps(route, ensure_ascii=False, indent=2))
    print("\nPlanner result")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print("\nRAG synthesis")
    print(rag["synthesis"]["answer"] if rag else f"Skipped: {route['rag_reason']}")


if __name__ == "__main__":
    main()
