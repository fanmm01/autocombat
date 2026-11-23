const MOBILE_UA_RE = /Android.+Mobile|iPhone|iPod|Windows Phone|BlackBerry|Opera Mini|IEMobile|HarmonyOS.+Phone|\bMobile\b/i;

export function useMobileLandscape(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false;
  }

  const navWithUaData = navigator as Navigator & {
    userAgentData?: { mobile?: boolean };
  };
  const uaDataMobile = navWithUaData.userAgentData?.mobile;
  const ua = navigator.userAgent || '';
  if (/iPad|Macintosh/i.test(ua) && navigator.maxTouchPoints > 1) {
    return false;
  }

  const hasTouch =
    (navigator.maxTouchPoints || 0) > 0 ||
    Boolean(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  if (!hasTouch) {
    return false;
  }

  return uaDataMobile === true || MOBILE_UA_RE.test(ua) ||
    Math.min(window.screen.width, window.screen.height) <= 540;
}
