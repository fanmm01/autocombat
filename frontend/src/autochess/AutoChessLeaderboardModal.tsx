import { useEffect, useState } from 'react';
import { Award, Coins, Crown, Flame, RefreshCw, Shield, Trophy, X } from 'lucide-react';
import { ApiError } from '../types';
import { fetchRankedLeaderboard } from './api';
import type { AutoChessAccount, AutoChessLeaderboardResponse, AutoChessRuleset } from './types';

const TIER_FILTERS = [
  { id: 'all', name: '全服总榜' },
  { id: 'king', name: '王者' },
  { id: 'diamond', name: '钻石' },
  { id: 'platinum', name: '铂金' },
  { id: 'gold', name: '黄金' },
  { id: 'silver', name: '白银' },
  { id: 'bronze', name: '青铜' },
] as const;

interface Props {
  open: boolean;
  ruleset?: AutoChessRuleset;
  account: AutoChessAccount | null;
  onClose: () => void;
  onRequestLogin?: () => void;
}

export function AutoChessLeaderboardModal({ open, account, onClose, onRequestLogin, ruleset = 'standard' }: Props) {
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [data, setData] = useState<AutoChessLeaderboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadBoard = async (tier: string) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetchRankedLeaderboard(tier, 100, ruleset);
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void loadBoard(tierFilter);
  }, [open, tierFilter, account?.id, ruleset]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const myEntry = data?.my_entry;

  return (
    <div
      className="ac-modal-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="星序自走棋全服排位排行榜"
    >
      <div className="ac-modal ac-lb-modal" onClick={e => e.stopPropagation()}>
        <div className="ac-modal-head">
          <div>
            <h3>
              <Trophy size={18} style={{ verticalAlign: '-3px', marginRight: 6, color: '#d97706' }} />
              {ruleset === 'half_hs' ? '半变身' : '标准'}排位排行榜
            </h3>
            <p>
              统计系统内全部已注册账号的实时排位积分、段位与胜率（共 {data?.total_players ?? '…'} 名棋手入榜）
            </p>
          </div>
          <div className="ac-hud-group">
            <button
              type="button"
              className="ac-btn ac-btn-sm"
              disabled={loading}
              onClick={() => void loadBoard(tierFilter)}
            >
              <RefreshCw size={14} /> 刷新
            </button>
            <button type="button" className="ac-btn ac-btn-ghost ac-btn-sm" onClick={onClose}>
              <X size={15} /> 关闭
            </button>
          </div>
        </div>

        {/* My rank banner */}
        {account && myEntry ? (
          <div className="ac-lb-my-banner">
            <div className="ac-lb-my-left">
              <span className="ac-lb-my-rank">我的全服排名 #{myEntry.rank}</span>
              <span className={`ac-tier-badge ac-tier-${myEntry.rank_info.tier_id}`}>
                {myEntry.rank_info.full_label}
              </span>
              <strong>{myEntry.total_lp} 分</strong>
            </div>
            <div className="ac-lb-my-right">
              <span>
                {myEntry.wins}/{myEntry.games} 胜 ({myEntry.win_rate}%)
              </span>
              <span>
                <Shield size={13} style={{ verticalAlign: '-2px' }} /> 保段卡 {myEntry.shield_cards}
              </span>
              <span>
                <Coins size={13} style={{ verticalAlign: '-2px' }} /> 金币 {myEntry.coins}
              </span>
            </div>
          </div>
        ) : (
          <div className="ac-lb-guest-banner">
            <span>登录后即可参加 8 人排位混战并登上全服积分榜。</span>
            {onRequestLogin && (
              <button
                type="button"
                className="ac-btn ac-btn-primary ac-btn-xs"
                onClick={() => {
                  onClose();
                  onRequestLogin();
                }}
              >
                去登录 / 注册
              </button>
            )}
          </div>
        )}

        {/* Tier filter tabs */}
        <div className="ac-lb-filters" role="tablist" aria-label="按段位筛选排行榜">
          {TIER_FILTERS.map(tf => {
            const count =
              tf.id === 'all'
                ? data?.total_players ?? 0
                : data?.tier_distribution?.[tf.id] ?? 0;
            return (
              <button
                key={tf.id}
                type="button"
                role="tab"
                aria-selected={tierFilter === tf.id}
                className={`ac-wiki-chip ${tierFilter === tf.id ? 'active' : ''}`}
                onClick={() => setTierFilter(tf.id)}
              >
                {tf.name} ({count})
              </button>
            );
          })}
        </div>

        {error && <div className="ac-banner ac-banner-err">{error}</div>}

        <div className="ac-lb-list-wrap">
          {loading && !data ? (
            <p className="muted" style={{ textAlign: 'center', padding: 24 }}>
              正在读取全服排行榜数据…
            </p>
          ) : !data?.entries.length ? (
            <p className="muted" style={{ textAlign: 'center', padding: 24 }}>
              当前该段位暂无玩家上榜，快来冲击榜首吧！
            </p>
          ) : (
            <div className="ac-lb-list">
              {data.entries.map(entry => {
                const isMe = account?.id === entry.account_id;
                const rankBadgeClass =
                  entry.rank === 1
                    ? 'top1'
                    : entry.rank === 2
                    ? 'top2'
                    : entry.rank === 3
                    ? 'top3'
                    : '';
                return (
                  <div key={entry.account_id} className={`ac-lb-row ${isMe ? 'me' : ''}`}>
                    <div className={`ac-lb-rank-num ${rankBadgeClass}`}>
                      {entry.rank <= 3 ? <Crown size={14} /> : null}#{entry.rank}
                    </div>
                    <div className="ac-lb-player">
                      <div className="ac-lb-name-line">
                        <strong>{entry.display_name}</strong>
                        <small className="muted">@{entry.username}</small>
                        {isMe && <span className="ac-lb-me-tag">我</span>}
                      </div>
                      <div className="ac-lb-sub-line">
                        <span className={`ac-tier-badge ac-tier-${entry.rank_info.tier_id}`}>
                          {entry.rank_info.full_label}
                        </span>
                        {entry.win_streak >= 2 && (
                          <span className="ac-lb-streak-pill">
                            <Flame size={12} /> {entry.win_streak}连胜
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="ac-lb-score">
                      <strong>{entry.total_lp} LP</strong>
                      <small className="muted">
                        <Award size={12} style={{ verticalAlign: '-2px' }} /> {entry.wins}/{entry.games}胜 ·{' '}
                        {entry.firsts}吃鸡 ({entry.win_rate}%)
                      </small>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
