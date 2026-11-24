export function readStorage<T = string>(key: string): T | null {
  try {
    const val = wx.getStorageSync<T>(key);
    if (val === '' || val === undefined || val === null) {
      return null;
    }
    return val;
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: unknown): void {
  try {
    wx.setStorageSync(key, value);
  } catch {
    // Ignore storage quota errors in sandboxed/private modes.
  }
}

export function deleteStorage(key: string): void {
  try {
    wx.removeStorageSync(key);
  } catch {
    // Ignore storage errors.
  }
}
