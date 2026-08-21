"use client";

import { BoxIcon, DownloadIcon, EyeIcon, FileTextIcon, RefreshCwIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getTaskStructure,
  listTaskFiles,
  listTaskStructures,
  previewTaskFile,
  type CatalystFile,
  type CatalystStructure,
  type StructureData,
} from "@/lib/catalyst-api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StructureViewer } from "@/components/structure-viewer";

export function FileCenter({ taskId }: { taskId?: string }) {
  const [files, setFiles] = useState<CatalystFile[]>([]);
  const [structures, setStructures] = useState<CatalystStructure[]>([]);
  const [preview, setPreview] = useState<{
    name: string;
    content: string | string[];
    truncated: boolean;
  } | null>(null);
  const [structure, setStructure] = useState<StructureData | null>(null);
  const [error, setError] = useState("");
  const grouped = useMemo(
    () =>
      files.reduce<Record<string, CatalystFile[]>>((value, file) => {
        (value[file.category] ??= []).push(file);
        return value;
      }, {}),
    [files],
  );
  const refresh = async () => {
    if (!taskId) return;
    try {
      const [nextFiles, nextStructures] = await Promise.all([
        listTaskFiles(taskId),
        listTaskStructures(taskId),
      ]);
      setFiles(nextFiles);
      setStructures(nextStructures);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  useEffect(() => {
    setFiles([]);
    setStructures([]);
    void refresh();
  }, [taskId]);
  if (!taskId) return <Empty text="选择一个任务后查看结构和计算文件。" />;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b px-3 py-3">
        <div>
          <p className="text-sm font-semibold">文件与结构</p>
          <p className="mt-1 text-xs text-muted-foreground">按 task_id 安全关联，不显示本机路径</p>
        </div>
        <Button size="icon-sm" variant="ghost" onClick={() => void refresh()} aria-label="刷新文件">
          <RefreshCwIcon className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {structures.length > 0 && (
          <section className="mb-5">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <BoxIcon className="size-4" />
              三维结构
            </h3>
            {structures.map((item) => (
              <button
                key={item.structure_id}
                type="button"
                className="mb-2 w-full border p-2 text-left text-sm hover:bg-muted"
                onClick={async () =>
                  taskId && setStructure(await getTaskStructure(taskId, item.structure_id))
                }
              >
                <span className="block font-semibold">{item.label}</span>
                <span className="text-xs text-sky-700">查看三维结构</span>
              </button>
            ))}
          </section>
        )}
        {Object.entries(grouped).map(([category, items]) => (
          <section key={category} className="mb-5">
            <h3 className="mb-2 text-sm font-semibold">{category}</h3>
            {items?.map((file) => (
              <article key={file.file_id} className="mb-2 border p-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{file.name}</p>
                    <p className="text-xs text-muted-foreground">{formatBytes(file.size_bytes)}</p>
                  </div>
                  <div className="flex gap-1">
                    {file.previewable && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`查看 ${file.name}`}
                        onClick={async () =>
                          setPreview(await previewTaskFile(taskId, file.file_id))
                        }
                      >
                        <EyeIcon className="size-4" />
                      </Button>
                    )}
                    {file.downloadable && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`下载 ${file.name}`}
                        onClick={() =>
                          window.open(
                            `/api/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(file.file_id)}/download`,
                            "_blank",
                          )
                        }
                      >
                        <DownloadIcon className="size-4" />
                      </Button>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </section>
        ))}
        {!files.length && !error && <Empty text="这个任务目前还没有可展示的本地文件。" />}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-h-[86vh] sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileTextIcon className="size-4" />
              {preview?.name}
            </DialogTitle>
            <DialogDescription>
              {preview?.truncated ? "大型结果文件仅显示末尾关键内容。" : "只读文件预览"}
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-[68vh] overflow-auto whitespace-pre-wrap break-words border bg-muted/30 p-4 font-mono text-xs leading-5">
            {Array.isArray(preview?.content) ? preview.content.join("\n") : preview?.content}
          </pre>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(structure)} onOpenChange={(open) => !open && setStructure(null)}>
        <DialogContent className="sm:max-w-[min(1100px,calc(100vw-4rem))]">
          <DialogHeader>
            <DialogTitle>{structure?.name} 三维结构</DialogTitle>
            <DialogDescription>
              拖动旋转，滚轮缩放，右键平移。晶胞边界和固定原子均已标记。
            </DialogDescription>
          </DialogHeader>
          {structure && <StructureViewer structure={structure} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="p-4 text-sm text-muted-foreground">{text}</p>;
}
function formatBytes(value: number) {
  return value < 1024
    ? `${value} B`
    : value < 1024 * 1024
      ? `${(value / 1024).toFixed(1)} KB`
      : `${(value / 1024 / 1024).toFixed(1)} MB`;
}
