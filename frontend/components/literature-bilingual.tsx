"use client";

import { LanguagesIcon, RefreshCwIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { technicalStatusLabel } from "@/lib/status-labels";
import type { LiteratureTranslation, ReviewItem } from "@/lib/review-types";

export function LiteratureBilingual({ item }: { item: ReviewItem }) {
  const [translation, setTranslation] = useState<LiteratureTranslation | null>(null);
  const [view, setView] = useState<"en" | "zh">("en");
  const [loading, setLoading] = useState(false);
  const title = String(item.title ?? "");
  const abstract = String(item.abstract ?? "");

  const translate = async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/literature/translations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doi: item.doi ?? "", title, abstract }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(payload.detail ?? `Translation request failed (${response.status})`);
      }
      const result = (await response.json()) as LiteratureTranslation;
      setTranslation(result);
      if (["translated", "cached"].includes(result.translation_status)) setView("zh");
    } catch (error) {
      setTranslation({
        title_en: title,
        title_zh: "",
        abstract_en: abstract,
        abstract_zh: "",
        translation_status: "failed",
        translation_source: "kimi_machine_translation",
        translation_cached: false,
        translation_error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mb-3">
      <p className="font-semibold">{title || "Untitled literature record"}</p>
      {translation?.title_zh && (
        <p className="mt-1 text-sm font-semibold text-muted-foreground">
          {translation.title_zh} <span className="font-normal">（机器翻译）</span>
        </p>
      )}
      {abstract && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="inline-flex border" aria-label="文献摘要语言">
              <button
                type="button"
                onClick={() => setView("en")}
                className={`px-2.5 py-1 text-xs ${view === "en" ? "bg-foreground text-background" : ""}`}
              >
                English original
              </button>
              <button
                type="button"
                onClick={() => translation?.abstract_zh && setView("zh")}
                disabled={!translation?.abstract_zh}
                className={`px-2.5 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-40 ${view === "zh" ? "bg-foreground text-background" : ""}`}
              >
                中文翻译
              </button>
            </div>
            <Button size="sm" variant="outline" onClick={() => void translate()} disabled={loading}>
              {translation?.translation_status === "failed" ? (
                <RefreshCwIcon className="size-3.5" />
              ) : (
                <LanguagesIcon className="size-3.5" />
              )}
              {loading ? "正在翻译" : translation ? "重新翻译" : "生成中文翻译"}
            </Button>
          </div>
          <p className="mt-2 whitespace-pre-line text-sm text-muted-foreground">
            {view === "zh" ? translation?.abstract_zh : abstract}
          </p>
        </>
      )}
      {translation && (
        <div className="mt-2 text-xs text-muted-foreground">
          <span>{technicalStatusLabel(translation.translation_status)}</span>
          <span> · Kimi 机器翻译，英文原文为准</span>
          {translation.translation_error && (
            <p className="mt-1 text-destructive">{translation.translation_error}</p>
          )}
        </div>
      )}
    </div>
  );
}
