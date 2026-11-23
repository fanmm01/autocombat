import { useEffect, useState } from 'react';
import { ArrowLeft, BookOpen, Diamond, Shield, X } from 'lucide-react';
import { readPreferences, savePreferences } from '../settings';
import { api } from '../types';
import { AutoChessPage } from './AutoChessPage';
import './autochess.css';

export function AutoChessApp({ onSwitchToClassic }: { onSwitchToClassic: () => void }) {
  const initialPrefs = readPreferences();
  const [name, setName] = useState(initialPrefs.name);
  const [reduced] = useState(initialPrefs.reduced);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [wikiOpenNonce, setWikiOpenNonce] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.reduced = String(reduced);
    localStorage.setItem('combat-reduced', String(reduced));
  }, [reduced]);

  useEffect(() => {
    let active = true;
    api<{ id: string }>('/session', { name })
      .then(() => {
        if (active) setConnected(true);
      })
      .catch(e => {
        if (active) setError((e as Error).message);
      });
    return () => {
      active = false;
    };
  }, []);

  const updatePlayerName = async (nextName: string) => {
    const cleaned = nextName.trim().slice(0, 20);
    if (!cleaned) {
      throw new Error('请填写指挥官称呼');
    }
    await api('/session', { name: cleaned });
    savePreferences({ name: cleaned, reduced });
    setName(cleaned);
    setConnected(true);
  };

  return (
    <div className="ac-shell">
      <header className="ac-topbar">
        <div className="ac-topbar-brand">
          <span className="ac-topbar-mark" aria-hidden="true">
            <Diamond size={18} strokeWidth={1.8} />
          </span>
          <div className="ac-topbar-title">
            <strong>星序自走棋</strong>
            <small>STARLIGHT AUTO-CHESS</small>
          </div>
        </div>

        <div className="ac-topbar-actions">
          <span className={'connection ' + (connected ? 'online' : '')}>
            <i />
            <span>{connected ? '引擎已连接' : '连接恢复中'}</span>
          </span>
          <span className="ac-topbar-user" title="当前指挥官">
            <span aria-hidden="true">{name.slice(0, 1)}</span>
            <em>{name}</em>
          </span>
          <button
            type="button"
            className="button subtle compact-button ac-topbar-wiki-btn"
            onClick={() => setWikiOpenNonce(n => n + 1)}
          >
            <BookOpen size={15} />
            <span>自走棋百科</span>
          </button>
          <button
            type="button"
            className="button subtle compact-button ac-mode-switch"
            onClick={onSwitchToClassic}
          >
            <ArrowLeft size={15} />
            <span>返回经典模式</span>
          </button>
        </div>
      </header>

      <main className="ac-main">
        {error && (
          <div className="error-banner" role="alert">
            <Shield size={17} />
            <span>{error}</span>
            <button onClick={() => setError('')} aria-label="关闭错误">
              <X size={16} />
            </button>
          </div>
        )}
        <AutoChessPage
          playerName={name}
          onPlayerNameChange={updatePlayerName}
          wikiOpenNonce={wikiOpenNonce}
          onError={setError}
        />
      </main>
    </div>
  );
}
