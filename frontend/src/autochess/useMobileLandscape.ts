import { useEffect, useState } from 'react';

const MOBILE_UA_RE = /Android.+Mobile|iPhone|iPod|Windows Phone|BlackBerry|Opera Mini|IEMobile|HarmonyOS.+Phone|\bMobile\b/i;

export function detectMobilePhoneLandscape(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false;
  }

  const navWithUaData = navigator as Navigator & {
    userAgentData?: { mobile?: boolean };
  };
  const uaDataMobile = navWithUaData.userAgentData?.mobile;
  const ua = navigator.userAgent || '';
  const isMobileUa = uaDataMobile === true || (uaDataMobile !== false && MOBILE_UA_RE.test(ua));
  if (!isMobileUa) {
    return false;
  }

  const hasTouch =
    (navigator.maxTouchPoints || 0) > 0 ||
    Boolean(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  if (!hasTouch) {
    return false;
  }

  const w = window.innerWidth;
  const h = window.innerHeight;
  return w > h && h <= 540 && w <= 1024;
}

export function useMobileLandscape(): boolean {
  const [active, setActive] = useState<boolean>(() => detectMobilePhoneLandscape());

  useEffect(() => {
    const sync = () => {
      setActive(detectMobilePhoneLandscape());
    };
    sync();
    window.addEventListener('resize', sync);
    window.addEventListener('orientationchange', sync);
    return () => {
      window.removeEventListener('resize', sync);
      window.removeEventListener('orientationchange', sync);
    };
  }, []);

  return active;
}
