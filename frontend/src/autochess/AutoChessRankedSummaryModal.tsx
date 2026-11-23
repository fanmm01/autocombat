import { Award, Coins, Shield, Sparkles, Trophy, X } from 'lucide-react';
import type { AutoChessRankedSettlement } from './types';

interface Props {
  settlement: AutoChessRankedSettlement | null;
  onClose: () => void;
  onPlayAgain: () => void;
  onOpenLeaderboard: () => void;
  onBackToLobby: () => void;
}

export function AutoChessRankedSummaryModal({
  settlement,
  onClose,
  onPlayAgain,
  onOpenLeaderboard,
  onBackToLobby,
}: Props) {
  if (!settlement) return null;

  const {
    placement,
    won,
    base_delta,
    streak_bonus,
    net_delta,
    win_streak,
    old_rank,
    new_rank,
    promoted,
    silver_floor_triggered,
    shield_card_used,
    shield_card_earned,
    shield_cards_after,
    coins_earned,
    coins_after,
  } = settlement;

  const outcomeTitle =
    placement === 1
      ? '🏆 第 1 名 · 登顶吃鸡！'
      : won
      ? `✨ 第 ${placement} / 8 名 · 排位胜利`
      : `第 ${placement} / 8 名 · 遗憾淘汰`;

  const netText = `${net_delta >= 0 ? '+' : ''}${net_delta}`;

  return (
    <div
      className="ac-modal-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="排位赛结算报告"
    >
      <div className="ac-modal ac-ranked-summary-modal" onClick={e => e.stopPropagation()}>
        <div className="ac-modal-head">
          <div>
            <div className="eyebrow">8-PLAYER RANKED SETTLEMENT</div>
            <h3 className={won ? 'ac-summary-win-title' : 'ac-summary-loss-title'}>{outcomeTitle}</h3>
          </div>
          <button type="button" className="ac-btn ac-btn-ghost ac-btn-sm" onClick={onClose}>
            <X size={15} />
          </button>
        </div>

        {/* Tier progression card */}
        <div className="ac-summary-rank-card">
          <div className="ac-summary-rank-top">
            <div>
              <span className={`ac-tier-badge ac-tier-${new_rank.tier_id}`}>{new_rank.full_label}</span>
              {promoted && (
                <span className="ac-summary-promo-pill">
                  🎉 {settlement.tier_changed ? '大段晋级!' : '小段晋升!'}
                </span>
              )}
            </div>
            <div className={`ac-summary-net ${net_delta >= 0 ? 'pos' : 'neg'}`}>{netText} LP</div>
          </div>

          <div className="ac-lp-progress-wrap">
            <div className="ac-lp-progress-bar">
              <div
                className="ac-lp-progress-fill"
                style={{
                  width: `${Math.min(100, Math.max(0, new_rank.division_lp))}%`,
                  backgroundColor: new_rank.tier_color,
                }}
              />
            </div>
            <div className="ac-lp-progress-labels">
              <span>
                {old_rank.full_label} ({settlement.old_lp}分) → {new_rank.full_label} ({settlement.new_lp}分)
              </span>
              <span>本阶进度 {new_rank.division_lp}/100</span>
            </div>
          </div>
        </div>

        {/* LP & Protection breakdown */}
        <div className="ac-summary-breakdown">
          <div className="ac-stat-card">
            <div className="ac-stat-label">名次基础分</div>
            <div className="ac-stat-val">
              {base_delta >= 0 ? '+' : ''}
              {base_delta}
            </div>
          </div>
          <div className="ac-stat-card">
            <div className="ac-stat-label">连胜额外加分</div>
            <div className="ac-stat-val">
              {streak_bonus > 0 ? `+${streak_bonus} (${win_streak}连胜)` : won ? `0 (${win_streak}连胜)` : '0 (已重置)'}
            </div>
          </div>
          <div className="ac-stat-card">
            <div className="ac-stat-label">
              <Coins size={12} style={{ verticalAlign: '-1px' }} /> 局外金币奖励
            </div>
            <div className="ac-stat-val" style={{ color: coins_earned > 0 ? '#b45309' : undefined }}>
              {coins_earned > 0 ? `+${coins_earned}` : '0'}（总计 {coins_after}）
            </div>
          </div>
          <div className="ac-stat-card">
            <div className="ac-stat-label">
              <Shield size={12} style={{ verticalAlign: '-1px' }} /> 当前保段卡
            </div>
            <div className="ac-stat-val">
              {shield_cards_after} 张{shield_card_earned > 0 ? ' (+1 获得!)' : ''}
            </div>
          </div>
        </div>

        {/* Special protection or reward banners */}
        {shield_card_used && (
          <div className="ac-banner ac-banner-ok">
            <Shield size={14} style={{ verticalAlign: '-2px', marginRight: 5 }} />
            <strong>保段卡已生效！</strong> 本局原本将会掉段，系统已自动消耗 1 张保段卡为你抵消全部扣分并保住原段位。
          </div>
        )}
        {silver_floor_triggered && (
          <div className="ac-banner ac-banner-ok">
            <Sparkles size={14} style={{ verticalAlign: '-2px', marginRight: 5 }} />
            <strong>白银段位永久保底触发！</strong> 达到白银后永不因战败跌回青铜（300 分以上，不消耗保段卡）。
          </div>
        )}
        {shield_card_earned > 0 && (
          <div className="ac-banner ac-banner-warn">
            <Award size={14} style={{ verticalAlign: '-2px', marginRight: 5 }} />
            达成 <strong>{win_streak} 连胜</strong>，额外获得 <strong>+1 张保段卡</strong>！
          </div>
        )}
        {coins_earned > 0 && (
          <div className="muted" style={{ fontSize: '0.76rem' }}>
            💡 局外资源「金币」已入账（当前共 {coins_after} 枚，暂未开放兑换出口）。
          </div>
        )}

        <div className="ac-modal-actions ac-modal-actions-between" style={{ flexWrap: 'wrap' }}>
          <div className="ac-hud-group">
            <button type="button" className="ac-btn ac-btn-sm" onClick={onOpenLeaderboard}>
              <Trophy size={14} /> 查看排行榜
            </button>
            <button type="button" className="ac-btn ac-btn-sm" onClick={onBackToLobby}>
              返回大厅
            </button>
          </div>
          <button type="button" className="ac-btn ac-btn-primary ac-btn-sm" onClick={onPlayAgain}>
            <Sparkles size={14} /> 再来一局排位
          </button>
        </div>
      </div>
    </div>
  );
}
