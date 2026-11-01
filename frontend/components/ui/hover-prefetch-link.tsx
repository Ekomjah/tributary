"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type FocusEvent,
  type PointerEvent,
} from "react";

type LinkProps = ComponentProps<typeof Link>;

interface HoverPrefetchLinkProps extends LinkProps {
  /** Called once the pointer or keyboard focus has rested here. */
  onIntent?: () => void;
  intentDelay?: number;
  /** Let Next prefetch the full route once intent is shown. */
  prefetchOnIntent?: boolean;
}

function canPrefetch(): boolean {
  if (typeof navigator !== "undefined") {
    const connection = (
      navigator as Navigator & { connection?: { saveData?: boolean } }
    ).connection;
    if (connection?.saveData) {
      return false;
    }
  }

  if (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(pointer: coarse)").matches
  ) {
    return false;
  }

  return true;
}

export default function HoverPrefetchLink({
  onIntent,
  intentDelay = 150,
  prefetchOnIntent = false,
  prefetch = false,
  onPointerEnter,
  onPointerLeave,
  onFocus,
  onBlur,
  ...props
}: HoverPrefetchLinkProps) {
  const timer = useRef<number | null>(null);
  const [intent, setIntent] = useState(false);

  const clear = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => clear, [clear]);

  const start = useCallback(() => {
    if (!canPrefetch()) {
      return;
    }

    if (prefetchOnIntent) {
      setIntent(true);
    }

    if (!onIntent || timer.current !== null) {
      return;
    }

    timer.current = window.setTimeout(() => {
      timer.current = null;
      onIntent();
    }, intentDelay);
  }, [intentDelay, onIntent, prefetchOnIntent]);

  return (
    <Link
      {...props}
      prefetch={intent ? true : prefetch}
      onPointerEnter={(event: PointerEvent<HTMLAnchorElement>) => {
        start();
        onPointerEnter?.(event);
      }}
      onPointerLeave={(event: PointerEvent<HTMLAnchorElement>) => {
        clear();
        onPointerLeave?.(event);
      }}
      onFocus={(event: FocusEvent<HTMLAnchorElement>) => {
        start();
        onFocus?.(event);
      }}
      onBlur={(event: FocusEvent<HTMLAnchorElement>) => {
        clear();
        onBlur?.(event);
      }}
    />
  );
}
