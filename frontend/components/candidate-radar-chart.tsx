"use client";

import { useState } from "react";

const DIMENSIONS = [
  ["literature_support", "文献支持", 0.25],
  ["constraint_preference", "约束偏好", 0.1],
  ["element_abundance", "元素丰度", 0.15],
  ["price", "价格", 0.2],
  ["toxicity_environment", "毒性环境", 0.15],
  ["synthesis_difficulty", "合成难度", 0.15],
] as const;

export function CandidateRadarChart({ scores }: { scores: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const values = DIMENSIONS.map(([key]) => clamp(Number(scores[key] ?? 0)));
  const center = 130;
  const radius = 82;
  const points = values
    .map((value, index) => polarPoint(index, radius * (value / 100), center))
    .map(([x, y]) => `${x},${y}`)
    .join(" ");

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="text-sm font-semibold text-sky-700 underline underline-offset-4 hover:text-sky-900"
      >
        {open ? "收起六维评分" : "查看六维评分雷达图"}
      </button>
      {open && (
        <div className="mt-3 grid max-w-2xl grid-cols-[280px_1fr] items-center gap-5 border-y py-3">
          <svg viewBox="0 0 260 260" role="img" aria-label="候选材料六维评分雷达图">
            {[20, 40, 60, 80, 100].map((level) => (
              <polygon
                key={level}
                points={DIMENSIONS.map((_, index) =>
                  polarPoint(index, radius * (level / 100), center).join(","),
                ).join(" ")}
                fill="none"
                stroke="#cbd5e1"
                strokeWidth="1"
              />
            ))}
            {DIMENSIONS.map(([, label], index) => {
              const [x, y] = polarPoint(index, radius, center);
              const [labelX, labelY] = polarPoint(index, radius + 27, center);
              return (
                <g key={label}>
                  <line x1={center} y1={center} x2={x} y2={y} stroke="#cbd5e1" />
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    className="fill-slate-700 text-[10px]"
                  >
                    {label}
                  </text>
                </g>
              );
            })}
            <polygon
              points={points}
              fill="#0ea5e9"
              fillOpacity="0.2"
              stroke="#0369a1"
              strokeWidth="2"
            />
            {values.map((value, index) => {
              const [x, y] = polarPoint(index, radius * (value / 100), center);
              return <circle key={DIMENSIONS[index][0]} cx={x} cy={y} r="3" fill="#0369a1" />;
            })}
          </svg>
          <dl className="grid gap-2 text-xs">
            {DIMENSIONS.map(([key, label, weight], index) => (
              <div key={key} className="grid grid-cols-[1fr_auto_auto] gap-3 border-b pb-1">
                <dt>{label}</dt>
                <dd>{values[index].toFixed(2)}</dd>
                <dd className="text-muted-foreground">权重 {(weight * 100).toFixed(0)}%</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

function polarPoint(index: number, radius: number, center: number): [number, number] {
  const angle = -Math.PI / 2 + (index * Math.PI * 2) / DIMENSIONS.length;
  return [center + Math.cos(angle) * radius, center + Math.sin(angle) * radius];
}

function clamp(value: number) {
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
}
