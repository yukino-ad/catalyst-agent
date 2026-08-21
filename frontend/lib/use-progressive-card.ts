"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export function useProgressiveCard(values: string[], animate: boolean, onComplete?: () => void) {
  const normalized = useMemo(() => values.map((value) => String(value ?? "")), [values]);
  const signature = normalized.join("\u0000");
  const total = normalized.reduce((sum, value) => sum + value.length, 0);
  const [visible, setVisible] = useState(animate ? 0 : total);
  const completeRef = useRef(onComplete);
  const completedSignatureRef = useRef<string | null>(null);
  completeRef.current = onComplete;

  useEffect(() => {
    const finish = () => {
      if (completedSignatureRef.current === signature) return;
      completedSignatureRef.current = signature;
      completeRef.current?.();
    };
    if (!animate) {
      setVisible((current) => (current === total ? current : total));
      finish();
      return;
    }
    setVisible((current) => (current === 0 ? current : 0));
    if (total === 0) {
      finish();
      return;
    }
    const chunkSize = Math.max(1, Math.ceil(total / 90));
    const timer = window.setInterval(() => {
      setVisible((current) => {
        const next = Math.min(total, current + chunkSize);
        if (next >= total) {
          window.clearInterval(timer);
          window.setTimeout(finish, 80);
        }
        return next;
      });
    }, 18);
    return () => window.clearInterval(timer);
  }, [animate, signature, total]);

  const text = useCallback(
    (index: number) => {
      const offset = normalized.slice(0, index).reduce((sum, value) => sum + value.length, 0);
      return normalized[index]?.slice(0, Math.max(0, visible - offset)) ?? "";
    },
    [normalized, visible],
  );

  return { text, complete: visible >= total };
}
