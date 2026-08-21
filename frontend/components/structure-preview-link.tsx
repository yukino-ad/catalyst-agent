"use client";

import { useState } from "react";
import { getTaskStructure, listTaskStructures, type StructureData } from "@/lib/catalyst-api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StructureViewer } from "@/components/structure-viewer";

export function StructurePreviewLink({
  taskId,
  structureLabel,
  linkLabel = "使用 ASE 风格查看器",
}: {
  taskId: string;
  structureLabel: string;
  linkLabel?: string;
}) {
  const [structure, setStructure] = useState<StructureData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const open = async () => {
    setLoading(true);
    try {
      const structures = await listTaskStructures(taskId);
      const wanted = compact(structureLabel);
      const match =
        structures.find((item) => {
          const label = compact(item.label);
          return label.includes(wanted) || wanted.includes(label);
        }) ?? structures.find((item) => compact(item.name).includes(wanted));
      if (!match) throw new Error("该任务尚未找到与此标识匹配的结构文件。");
      setStructure(await getTaskStructure(taskId, match.structure_id));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };
  return (
    <>
      <button
        type="button"
        onClick={() => void open()}
        disabled={loading}
        className="mt-2 text-sm font-semibold text-sky-700 underline underline-offset-4 hover:text-sky-900 disabled:opacity-50"
      >
        {loading ? "正在读取结构" : linkLabel}
      </button>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      <Dialog open={Boolean(structure)} onOpenChange={(value) => !value && setStructure(null)}>
        <DialogContent className="sm:max-w-[min(1100px,calc(100vw-4rem))]">
          <DialogHeader>
            <DialogTitle>{structureLabel}</DialogTitle>
            <DialogDescription>
              ASE 解析语义与网页三维交互：拖动旋转，滚轮缩放，右键平移。
            </DialogDescription>
          </DialogHeader>
          {structure && <StructureViewer structure={structure} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function compact(value: string) {
  return value.toLocaleLowerCase("en-US").replace(/[^a-z0-9]/g, "");
}
