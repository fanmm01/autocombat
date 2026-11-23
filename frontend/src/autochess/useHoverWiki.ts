import { useCallback, useEffect, useRef, useState } from 'react';

export const WIKI_HOVER_DELAY_MS = 1500;
const WIKI_LEAVE_GRACE_MS = 240;

export interface HoverAnchorRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface HoverWikiPreview {
  serial: string;
  star: number;
  rect: HoverAnchorRect;
}

function toAnchorRect(r: DOMRect): HoverAnchorRect {
  return {
    left: r.left,
    top: r.top,
    right: r.right,
    bottom: r.bottom,
    width: r.width,
    height: r.height,
  };
}

function isPureTouchViewport(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia('(hover: none) and (pointer: coarse)').matches;
}

export function useHoverWiki() {
  const [preview, setPreview] = useState<HoverWikiPreview | null>(null);
  const openTimerRef = useRef<number | null>(null);
  const closeTimerRef = useRef<number | null>(null);

  const clearOpenTimer = useCallback(() => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
  }, []);

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const closeNow = useCallback(() => {
    clearOpenTimer();
    clearCloseTimer();
    setPreview(null);
  }, [clearOpenTimer, clearCloseTimer]);

  const startHover = useCallback(
    (serial: string, star: number, target: Element | null) => {
      if (!serial || !target || isPureTouchViewport()) return;
      clearOpenTimer();
      clearCloseTimer();
      const initialRect = toAnchorRect(target.getBoundingClientRect());
      openTimerRef.current = window.setTimeout(() => {
        openTimerRef.current = null;
        const rect = target.isConnected ? toAnchorRect(target.getBoundingClientRect()) : initialRect;
        if (rect.width <= 0 && rect.height <= 0) return;
        setPreview({ serial, star: Math.max(1, Math.min(3, star || 1)), rect });
      }, WIKI_HOVER_DELAY_MS);
    },
    [clearOpenTimer, clearCloseTimer],
  );

  const leaveTarget = useCallback(() => {
    clearOpenTimer();
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      setPreview(null);
    }, WIKI_LEAVE_GRACE_MS);
  }, [clearOpenTimer, clearCloseTimer]);

  const enterPopover = useCallback(() => {
    clearCloseTimer();
  }, [clearCloseTimer]);

  const leavePopover = useCallback(() => {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      setPreview(null);
    }, 180);
  }, [clearCloseTimer]);

  useEffect(() => {
    if (!preview) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeNow();
    };
    const onScroll = (e: Event) => {
      const target = e.target as Element | null;
      if (target && typeof target.closest === 'function' && target.closest('.ac-wiki-popover')) {
        return;
      }
      closeNow();
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [preview, closeNow]);

  useEffect(() => {
    return () => {
      clearOpenTimer();
      clearCloseTimer();
    };
  }, [clearOpenTimer, clearCloseTimer]);

  return {
    preview,
    startHover,
    leaveTarget,
    enterPopover,
    leavePopover,
    closeNow,
  };
}
