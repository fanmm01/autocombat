import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../types';
import { clearGuestToken, resetUnitToken, saveGuestToken, setUnitToken } from './api';
import type { AutoChessAccount, AutoChessCatalog, AutoChessUnitMeta } from './types';

interface Props {
  open: boolean;
  catalog: AutoChessCatalog | null;
  account: AutoChessAccount | null;
  guestTokens: Record<string, string>;
  initialSerial?: string | null;
  onClose: () => void;
  onAccountUpdate: (account: AutoChessAccount) => void;
  onGuestTokensUpdate: (tokens: Record<string, string>) => void;
}

const COST_COLORS: Record<number, string> = {
  1: '#8b9bb4',
  2: '#39b980',
  3: '#4a90e2',
  4: '#b064e8',
  5: '#f0b23a',
};

function cropFileToTokenDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('读取图片文件失败'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('无法解析该图片格式'));
      img.onload = () => {
        const side = Math.min(img.width, img.height);
        if (side <= 0) {
          reject(new Error('图片尺寸无效'));
          return;
        }
        const sx = Math.floor((img.width - side) / 2);
        const sy = Math.floor((img.height - side) / 2);
        const canvas = document.createElement('canvas');
        canvas.width = 128;
        canvas.height = 128;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('浏览器不支持画布裁剪'));
          return;
        }
        ctx.drawImage(img, sx, sy, side, side, 0, 0, 128, 128);
        let url = canvas.toDataURL('image/webp', 0.85);
        if (!url.startsWith('data:image/webp')) {
          url = canvas.toDataURL('image/png');
        }
        if (url.length > 235_000) {
          url = canvas.toDataURL('image/jpeg', 0.78);
        }
        resolve(url);
      };
      img.src = String(reader.result || '');
    };
    reader.readAsDataURL(file);
  });
}

export function AutoChessTokenModal({
  open,
  catalog,
  account,
  guestTokens,
  initialSerial,
  onClose,
  onAccountUpdate,
  onGuestTokensUpdate,
}: Props) {
  const units = useMemo(
    () =>
      [...(catalog?.units || [])].sort(
        (a, b) => a.cost - b.cost || a.serial.localeCompare(b.serial, undefined, { numeric: true }),
      ),
    [catalog],
  );
  const emblems = useMemo(() => catalog?.available_emblems || [], [catalog]);
  const [selectedSerial, setSelectedSerial] = useState<string>('Y1');
  const [previewSide, setPreviewSide] = useState<'Y' | 'X'>('Y');
  const [urlInput, setUrlInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const fileRef = useRef<HTMLInputElement | null>(null);

  const activeOverrides = account ? account.token_overrides || {} : guestTokens;

  useEffect(() => {
    if (!open) return;
    setError('');
    setNotice('');
    if (initialSerial && units.some(u => u.serial === initialSerial)) {
      setSelectedSerial(initialSerial);
    } else if (units.length && !units.some(u => u.serial === selectedSerial)) {
      setSelectedSerial(units[0].serial);
    }
  }, [open, initialSerial, units]);

  useEffect(() => {
    const currentCustom = activeOverrides[selectedSerial] || '';
    setUrlInput(currentCustom.startsWith('data:') ? '' : currentCustom);
  }, [selectedSerial, activeOverrides]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const selectedUnit: AutoChessUnitMeta | undefined = units.find(u => u.serial === selectedSerial) || units[0];
  const currentUrl =
    (selectedUnit && activeOverrides[selectedUnit.serial]) || selectedUnit?.emblem_url || '/ui/icons/flame.svg';
  const hasCustom = Boolean(selectedUnit && activeOverrides[selectedUnit.serial]);

  async function applyToken(serial: string, tokenUrl: string) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      if (account) {
        const res = await setUnitToken(serial, tokenUrl);
        onAccountUpdate(res.account);
        setNotice(`已保存 ${selectedUnit?.name || serial} 的棋子头图并同步至数据库`);
      } else {
        const next = saveGuestToken(serial, tokenUrl);
        onGuestTokensUpdate(next);
        setNotice(`已更新 ${selectedUnit?.name || serial} 的本机棋子头图`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset(serial: string) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      if (account) {
        const res = await resetUnitToken(serial);
        onAccountUpdate(res.account);
      } else {
        const next = clearGuestToken(serial);
        onGuestTokensUpdate(next);
      }
      setNotice(`已恢复 ${selectedUnit?.name || serial} 为默认徽章`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file || !selectedUnit) return;
    setError('');
    try {
      const dataUrl = await cropFileToTokenDataUrl(file);
      await applyToken(selectedUnit.serial, dataUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const ringColor = previewSide === 'Y' ? '#5b46e8' : '#df4e3b';

  return (
    <div className="ac-modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="定制棋子头图">
      <div className="ac-modal ac-token-modal" onClick={e => e.stopPropagation()}>
        <div className="ac-modal-head">
          <div>
            <h3>定制棋子 Token 头图</h3>
            <p>
              场上棋子外圈固定显示分队色彩（友方靛蓝 / 敌方绯红），顶部标注角色名；你可自由更换每枚棋子的圆形头图或主程序徽章。
            </p>
          </div>
          <button type="button" className="ac-btn ac-btn-ghost ac-btn-sm" onClick={onClose}>
            ✕ 关闭
          </button>
        </div>

        {error && <div className="ac-banner ac-banner-err">{error}</div>}
        {notice && <div className="ac-banner ac-banner-ok">{notice}</div>}

        <div className="ac-token-layout">
          <div className="ac-token-roster" role="listbox" aria-label="选择棋子">
            {units.map(u => {
              const uUrl = activeOverrides[u.serial] || u.emblem_url || '/ui/icons/flame.svg';
              const isSvg = uUrl.toLowerCase().endsWith('.svg');
              const active = u.serial === selectedUnit?.serial;
              const customized = Boolean(activeOverrides[u.serial]);
              return (
                <button
                  key={u.serial}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`ac-token-unit-btn ${active ? 'active' : ''}`}
                  onClick={() => setSelectedSerial(u.serial)}
                >
                  <span className="ac-token-mini-ring" style={{ borderColor: '#5b46e8' }}>
                    {isSvg ? (
                      <span
                        className="ac-token-mini-emblem"
                        style={{
                          backgroundColor: u.accent || '#a7a0e8',
                          WebkitMaskImage: `url(${uUrl})`,
                          maskImage: `url(${uUrl})`,
                        }}
                      />
                    ) : (
                      <img src={uUrl} alt={u.name} className="ac-token-mini-img" />
                    )}
                  </span>
                  <span className="ac-token-unit-info">
                    <span className="ac-token-unit-name">{u.name}</span>
                    <span className="ac-token-unit-cost" style={{ color: COST_COLORS[u.cost] || '#ccc' }}>
                      {u.cost}费 · {u.serial}
                    </span>
                  </span>
                  {customized && <span className="ac-token-custom-dot" title="已定制">改</span>}
                </button>
              );
            })}
          </div>

          {selectedUnit && (
            <div className="ac-token-editor">
              <div className="ac-token-preview-stage">
                <div className="ac-token-stage-controls">
                  <span>预览分队环：</span>
                  <button
                    type="button"
                    className={`ac-btn ac-btn-xs ${previewSide === 'Y' ? 'ac-btn-primary' : 'ac-btn-ghost'}`}
                    onClick={() => setPreviewSide('Y')}
                  >
                    友方（固定靛蓝）
                  </button>
                  <button
                    type="button"
                    className={`ac-btn ac-btn-xs ${previewSide === 'X' ? 'ac-btn-danger' : 'ac-btn-ghost'}`}
                    onClick={() => setPreviewSide('X')}
                  >
                    敌方（固定绯红）
                  </button>
                </div>

                <div className="ac-token-board-mock">
                  <div className="ac-token-mock-name">{selectedUnit.name}</div>
                  <div
                    className="ac-token-mock-ring"
                    style={{
                      borderColor: ringColor,
                      boxShadow: `0 0 0 3px ${ringColor}33, 0 8px 20px rgba(0,0,0,0.45)`,
                    }}
                  >
                    {currentUrl.toLowerCase().endsWith('.svg') ? (
                      <span
                        className="ac-token-mock-emblem"
                        style={{
                          backgroundColor: selectedUnit.accent || '#f5ede4',
                          WebkitMaskImage: `url(${currentUrl})`,
                          maskImage: `url(${currentUrl})`,
                        }}
                      />
                    ) : (
                      <img src={currentUrl} alt={selectedUnit.name} className="ac-token-mock-img" />
                    )}
                  </div>
                  <div className="ac-token-mock-stars">★ {selectedUnit.cost}费</div>
                </div>
              </div>

              <div className="ac-token-actions-group">
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  style={{ display: 'none' }}
                  onChange={handleFileChange}
                />
                <button
                  type="button"
                  className="ac-btn ac-btn-primary ac-btn-sm"
                  onClick={() => fileRef.current?.click()}
                  disabled={busy}
                >
                  上传本地图片（自动居中裁成 128×128）
                </button>
                {hasCustom && (
                  <button
                    type="button"
                    className="ac-btn ac-btn-ghost ac-btn-sm"
                    onClick={() => handleReset(selectedUnit.serial)}
                    disabled={busy}
                  >
                    恢复默认徽章
                  </button>
                )}
              </div>

              <form
                className="ac-token-url-form"
                onSubmit={e => {
                  e.preventDefault();
                  const val = urlInput.trim();
                  if (val) applyToken(selectedUnit.serial, val);
                }}
              >
                <input
                  type="text"
                  placeholder="粘贴自定义头像 URL（https://... 或 /ui/icons/...svg）"
                  value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                />
                <button type="submit" className="ac-btn ac-btn-sm" disabled={busy || !urlInput.trim()}>
                  应用链接
                </button>
              </form>

              <div className="ac-token-emblem-section">
                <div className="ac-token-emblem-title">或换用主程序同款 17 套专属徽章：</div>
                <div className="ac-token-emblem-grid">
                  {emblems.map(item => (
                    <button
                      key={item.emblem}
                      type="button"
                      className={`ac-token-emblem-btn ${currentUrl === item.url ? 'active' : ''}`}
                      onClick={() => applyToken(selectedUnit.serial, item.url)}
                      disabled={busy}
                      title={`${item.label}（${item.emblem}）`}
                    >
                      <span
                        className="ac-token-emblem-icon"
                        style={{
                          WebkitMaskImage: `url(${item.url})`,
                          maskImage: `url(${item.url})`,
                        }}
                      />
                      <span>{item.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="ac-auth-foot-note">
                {account
                  ? '已登录：头图定制已存入 SQLite 数据库，多端同步且在多人联机对战中对对手可见。'
                  : '游客模式：当前定制仅保存于本机浏览器缓存；登录账号后可跨设备互通并在联机中展示。'}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
