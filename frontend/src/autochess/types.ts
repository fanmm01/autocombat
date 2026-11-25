export type AutoChessRuleset = 'standard' | 'half_hs';

export interface AutoChessUnitMeta {
  serial: string;
  name: string;
  cost: number;
  role: 'tank' | 'bruiser' | 'assassin' | 'ranged' | 'support' | 'summoner' | string;
  traits: string[];
  range: number;
  tag: string;
  blurb: string;
  emblem?: string;
  accent?: string;
  emblem_url?: string;
  default_token_url?: string;
}

export interface AutoChessEmblemOption {
  emblem: string;
  url: string;
  label: string;
  serial: string;
}

export interface AutoChessSynergyTier {
  count: number;
  label: string;
}

export interface AutoChessSynergyDef {
  id: string;
  name: string;
  icon: string;
  desc: string;
  tiers: AutoChessSynergyTier[];
}

export interface AutoChessActiveSynergy {
  id: string;
  name: string;
  icon: string;
  count: number;
  next_tier: number | null;
  max_tier: number;
  active_tier: AutoChessSynergyTier | null;
  desc: string;
}

export interface AutoChessAugment {
  id: string;
  name: string;
  tier?: string;
  desc?: string;
}

export interface AutoChessArenaPreset {
  id: string;
  name: string;
  description: string;
  width: number;
  height: number;
  deploy_cols: Record<string, number[]>;
  terrain: Record<string, 'wall' | 'cover' | 'leyline'>;
}

export interface AutoChessShopSlot {
  slot_index: number;
  serial: string;
  name: string;
  cost: number;
  role: string;
  traits: string[];
  tag: string;
  blurb: string;
  bought: boolean;
  hint: string | null;
}

export interface AutoChessOwnedUnit {
  id: string;
  serial: string;
  name: string;
  cost: number;
  role: string;
  traits: string[];
  range: number;
  tag: string;
  star: number;
  location: 'bench' | 'board';
  bench_idx: number | null;
  coord: string | null;
  stance: 'aggressive' | 'balanced' | 'defensive';
}

export interface AutoChessCommanderSummary {
  id: string;
  name: string;
  account_id?: string | null;
  is_human: boolean;
  ai_style_label?: string;
  ready?: boolean;
  next_ready?: boolean;
  skip_combat?: boolean;
  personality: string;
  hp: number;
  max_hp: number;
  gold: number;
  level: number;
  xp: number;
  xp_to_next: number;
  max_pop: number;
  board_count: number;
  streak: number;
  wins: number;
  losses: number;
  eliminated: boolean;
  placement: number | null;
  augments: AutoChessAugment[];
  synergies: AutoChessActiveSynergy[];
}

export interface AutoChessCombatUnit {
  uid: string;
  name: string;
  serial: string;
  team: 'Y' | 'X';
  coord: string;
  hp: number;
  max_hp: number;
  mp: number;
  shield: number;
  flying: boolean;
  dying: boolean;
  is_summon: boolean;
  coord_history: string[];
}

export interface AutoChessCombatSnapshot {
  round: number;
  overtime_start_round: number;
  width: number;
  height: number;
  terrain: Record<string, 'wall' | 'cover' | 'leyline'>;
  deploy_cols: Record<string, number[]>;
  units: AutoChessCombatUnit[];
}

export type AutoChessVfxKind = 'fire' | 'frost' | 'star' | 'blood' | 'heal' | 'summon' | 'slash';

export interface AutoChessVfxPopup {
  uid: string;
  coord: string;
  text: string;
  kind: 'dmg' | 'heal' | 'shield' | 'summon' | 'miss';
}

export interface AutoChessVfxEvent {
  type: 'move' | 'action';
  uid?: string;
  actor_uid?: string;
  from_coord?: string;
  to_coord?: string;
  path?: string[];
  flying?: boolean;
  target_uids?: string[];
  to_coords?: string[];
  skill_name?: string;
  vfx_kind?: AutoChessVfxKind;
  popups?: AutoChessVfxPopup[];
}

export interface AutoChessCombatFrame {
  round: number;
  actor_uid: string | null;
  actor_name: string;
  team: 'Y' | 'X';
  cmd: string;
  reason: string;
  lines: string[];
  vfx_events?: AutoChessVfxEvent[];
  snapshot: AutoChessCombatSnapshot;
}

export interface AutoChessTelemetryRow {
  uid: string;
  name: string;
  serial: string;
  team: 'Y' | 'X';
  dmg_dealt: number;
  dmg_taken: number;
  heal_done: number;
  shield_absorbed: number;
  tiles_moved: number;
  kills: number;
  alive: boolean;
}

export interface AutoChessRoundReport {
  round: number;
  opponent_name: string;
  won: boolean;
  battle_rounds: number;
  timeout: boolean;
  hp_damage: number;
  telemetry: AutoChessTelemetryRow[];
  mvp: AutoChessTelemetryRow | null;
}

export interface AutoChessMatchState {
  ruleset?: AutoChessRuleset;
  id: string;
  mode: 'lobby4' | 'pve12' | 'pvp_room' | 'ranked';
  ranked_tier?: string | null;
  ranked_settlement?: AutoChessRankedSettlement | null;
  arena_preset: string;
  arena_name: string;
  round_num: number;
  prep_deadline?: number;
  round_result_deadline?: number | null;
  max_waves: number | null;
  phase: 'prep' | 'combat' | 'round_result' | 'finished';
  winner_id: string | null;
  watching_cid?: string;
  opponent_name?: string;
  bout_token_overrides?: {
    Y: Record<string, string>;
    X: Record<string, string>;
  };
  map: {
    width: number;
    height: number;
    deploy_cols: Record<string, number[]>;
    terrain: Record<string, 'wall' | 'cover' | 'leyline'>;
  };
  player: {
    id: string;
    name: string;
    account_id?: string | null;
    ready?: boolean;
    next_ready?: boolean;
    skip_combat?: boolean;
    token_overrides?: Record<string, string>;
    hp: number;
    max_hp: number;
    gold: number;
    level: number;
    xp: number;
    xp_to_next: number;
    max_pop: number;
    max_interest: number;
    free_rerolls: number;
    streak: number;
    shop_locked: boolean;
    shop: (AutoChessShopSlot | null)[];
    board: AutoChessOwnedUnit[];
    bench: AutoChessOwnedUnit[];
    bench_capacity?: number;
    synergies: AutoChessActiveSynergy[];
    augments: AutoChessAugment[];
    pending_augments: AutoChessAugment[];
    placement: number | null;
  };
  commanders: AutoChessCommanderSummary[];
  combat_frames: AutoChessCombatFrame[];
  live_snapshot: AutoChessCombatSnapshot | null;
  last_round_report: AutoChessRoundReport | null;
  logs: string[];
  pool_remaining: number;
}

export interface AutoChessMatchSummary {
  ruleset?: AutoChessRuleset;
  id: string;
  mode: 'lobby4' | 'pve12' | 'ranked';
  ranked_tier?: string | null;
  arena_preset: string;
  round_num: number;
  phase: string;
  hp: number;
  updated_at: number;
}

export interface AutoChessStarStat {
  star: number;
  hp: number;
  mp: number;
  skill_bonus: number;
  flat_dmg: number;
  flat_dr: number;
  dodge: number;
  summon_hp_mult: number;
  summon_skill_bonus: number;
}

export interface AutoChessWikiSkill {
  name: string;
  timing: string;
  phase: number;
  phase_label: string;
  mp_cost: number | string;
  range: number | null;
  cooldown: number;
  summary: string;
}

export interface AutoChessUnitWiki {
  serial: string;
  name: string;
  cost: number;
  pool_count: number;
  role: string;
  traits: string[];
  range: number;
  tag: string;
  blurb: string;
  emblem?: string;
  accent?: string;
  emblem_url?: string;
  default_token_url?: string;
  mov: number;
  tactical_move: number;
  main_actions: number;
  dex: number;
  dodge: number;
  can_block: boolean;
  block_val: number;
  flying: boolean;
  tuning_notes: string[];
  star_stats: Record<string, AutoChessStarStat>;
  basic_attack: {
    skill_name: string;
    skill_val: number;
    dice: string;
    pierce: boolean;
  };
  passives: string[];
  skills: AutoChessWikiSkill[];
  lore?: AutoChessUnitLore | null;
}

export interface AutoChessLoreField {
  label: string;
  value: string;
}

export interface AutoChessExtraStoryRef {
  id: string;
  title: string;
  word_count: number;
}

export interface AutoChessUnitLore {
  serial: string;
  profile_fields: AutoChessLoreField[];
  story_mode: 'none' | 'inline' | 'jump';
  story_id?: string | null;
  story_text?: string;
  story_excerpt?: string;
  extra_stories?: AutoChessExtraStoryRef[];
}

export interface AutoChessStoryChapterMeta {
  id: string;
  title: string;
  word_count: number;
}

export interface AutoChessStoryParagraph {
  kind: 'narrator' | 'dialogue' | 'heading' | 'quote' | 'note' | 'divider';
  speaker?: string;
  text: string;
}

export interface AutoChessStoryChapter extends AutoChessStoryChapterMeta {
  paragraphs?: AutoChessStoryParagraph[];
}

export interface AutoChessStoryIndexItem {
  id: string;
  category: 'opening' | 'prequel' | 'character' | string;
  category_label: string;
  title: string;
  subtitle?: string;
  serial?: string | null;
  unit_name?: string | null;
  summary: string;
  word_count: number;
  is_long: boolean;
  chapter_count: number;
  chapters: AutoChessStoryChapterMeta[];
}

export interface AutoChessStoryDetail extends Omit<AutoChessStoryIndexItem, 'chapters'> {
  active_chapter_id: string;
  chapters: AutoChessStoryChapter[];
}

export const AUTOCHESS_ROLE_LABELS: Record<string, string> = {
  tank: '重装',
  bruiser: '斗士',
  assassin: '刺客',
  ranged: '射手',
  support: '辅助',
  summoner: '召唤',
};

export type AutoChessWikiTab = 'units' | 'synergies' | 'augments' | 'rules' | 'stories';

export interface AutoChessWikiTarget {
  tab: AutoChessWikiTab;
  serial?: string;
  synergyId?: string;
  storyId?: string;
  chapterId?: string;
}

export function resolveUnitWiki(catalog: AutoChessCatalog | null, serial: string): AutoChessUnitWiki | null {
  if (!catalog || !serial) return null;
  if (catalog.wiki_units && catalog.wiki_units[serial]) {
    return catalog.wiki_units[serial];
  }
  const meta = catalog.units.find(u => u.serial === serial);
  if (!meta) return null;
  return {
    serial: meta.serial,
    name: meta.name,
    cost: meta.cost,
    pool_count: catalog.pool_counts?.[String(meta.cost)] ?? 0,
    role: meta.role,
    traits: meta.traits,
    range: meta.range,
    tag: meta.tag,
    blurb: meta.blurb,
    mov: 8,
    tactical_move: 4,
    main_actions: 1,
    dex: 60,
    dodge: 50,
    can_block: false,
    block_val: 0,
    flying: serial === 'Y5' || serial === 'Y13',
    tuning_notes: [],
    star_stats: {
      '1': {
        star: 1,
        hp: 10,
        mp: 10,
        skill_bonus: 0,
        flat_dmg: 0,
        flat_dr: 0,
        dodge: 50,
        summon_hp_mult: 1,
        summon_skill_bonus: 0,
      },
    },
    basic_attack: { skill_name: '斗殴', skill_val: 50, dice: '1d4', pierce: false },
    passives: [],
    skills: [],
    lore: null,
  };
}

export interface AutoChessCatalog {
  ruleset?: AutoChessRuleset;
  units: AutoChessUnitMeta[];
  available_emblems?: AutoChessEmblemOption[];
  wiki_units?: Record<string, AutoChessUnitWiki>;
  story_index?: AutoChessStoryIndexItem[];
  synergies: AutoChessSynergyDef[];
  augments: AutoChessAugment[];
  arenas: AutoChessArenaPreset[];
  terrains: Record<string, string | { name?: string; summary?: string }>;
  levels: Record<string, { max_pop: number; xp_to_next: number; odds: Record<string, number> }>;
  pool_counts: Record<string, number>;
  pool_counts_8p?: Record<string, number>;
  ranked_rules?: {
    silver_floor_lp: number;
    shield_card_cap: number;
    win_streak_lp_bonus: Record<string, number>;
    base_win_coins: Record<string, number>;
    tiers: AutoChessRankedTierRule[];
  };
  star_scaling?: Record<
    string,
    {
      hp_mult: number;
      mp_mult: number;
      skill_bonus: number;
      flat_dmg: number;
      flat_dr: number;
      summon_hp_mult: number;
      summon_skill_bonus: number;
    }
  >;
}

export interface AutoChessRankedTierRule {
  id: string;
  name: string;
  divisions: number | null;
  division_labels: string[];
  base_lp: number;
  color: string;
  lp_table: number[];
  coin_mult: number;
}

export interface AutoChessRankInfo {
  total_lp: number;
  tier_id: 'bronze' | 'silver' | 'gold' | 'platinum' | 'diamond' | 'king' | string;
  tier_name: string;
  tier_color: string;
  division_index: number;
  division_label: string;
  full_label: string;
  division_lp: number;
  next_division_lp: number;
  king_level: number | null;
  silver_floor_unlocked: boolean;
}

export interface AutoChessRankedHistoryItem {
  match_id: string | null;
  placement: number;
  old_lp: number;
  new_lp: number;
  net_delta: number;
  tier_label: string;
  coins_earned: number;
  shield_card_used: boolean;
  shield_card_earned: number;
  timestamp: number;
}

export interface AutoChessRankedProfile {
  total_lp: number;
  peak_lp: number;
  silver_floor_unlocked: boolean;
  win_streak: number;
  best_win_streak: number;
  shield_cards: number;
  shield_card_cap: number;
  games: number;
  wins: number;
  firsts: number;
  coins: number;
  history: AutoChessRankedHistoryItem[];
  rank_info: AutoChessRankInfo;
}

export interface AutoChessRankedSettlement {
  match_id: string | null;
  placement: number;
  won: boolean;
  old_lp: number;
  new_lp: number;
  base_delta: number;
  streak_bonus: number;
  net_delta: number;
  win_streak: number;
  old_rank: AutoChessRankInfo;
  new_rank: AutoChessRankInfo;
  promoted: boolean;
  demoted: boolean;
  tier_changed: boolean;
  silver_floor_triggered: boolean;
  shield_card_used: boolean;
  shield_card_earned: number;
  shield_cards_after: number;
  coins_earned: number;
  coins_after: number;
}

export interface AutoChessLeaderboardEntry {
  rank: number;
  account_id: string;
  username: string;
  display_name: string;
  total_lp: number;
  peak_lp: number;
  rank_info: AutoChessRankInfo;
  games: number;
  wins: number;
  firsts: number;
  win_rate: number;
  win_streak: number;
  shield_cards: number;
  coins: number;
  silver_floor_unlocked: boolean;
}

export interface AutoChessLeaderboardResponse {
  ruleset?: AutoChessRuleset;
  entries: AutoChessLeaderboardEntry[];
  total_players: number;
  filtered_total: number;
  tier_distribution: Record<string, number>;
  my_rank: number | null;
  my_entry: AutoChessLeaderboardEntry | null;
}

export type AccountRole = 'user' | 'admin' | 'super_admin';

export type AdminPermission =
  | 'player_manage'
  | 'story_manage'
  | 'server_manage'
  | 'character_manage';

export interface AutoChessAccountStats {
  games: number;
  wins: number;
  top2: number;
  pve_clears: number;
}

export interface AutoChessAccount {
  id: string;
  username: string;
  display_name: string;
  role?: AccountRole;
  role_label?: string;
  permissions?: AdminPermission[];
  can_edit?: boolean;
  is_super_admin?: boolean;
  token_overrides: Record<string, string>;
  stats: AutoChessAccountStats;
  ranked?: AutoChessRankedProfile;
  ranked_half_hs?: AutoChessRankedProfile;
  created_at: number;
  wx_bound?: boolean;
}

export interface AutoChessAuthState {
  authenticated: boolean;
  account: AutoChessAccount | null;
}

export interface AutoChessRoomMember {
  account_id: string;
  username: string;
  display_name: string;
  ready: boolean;
  is_host: boolean;
}

export interface AutoChessRoomSummary {
  code: string;
  name: string;
  status: 'waiting' | 'playing' | 'finished';
  arena_preset: string;
  max_players: number;
  fill_bots: boolean;
  prep_duration: number;
  member_count: number;
  host_name: string;
  is_member: boolean;
  updated_at: number;
}

export interface AutoChessRoomState {
  code: string;
  name: string;
  status: 'waiting' | 'playing' | 'finished';
  arena_preset: string;
  max_players: number;
  fill_bots: boolean;
  prep_duration: number;
  auto_step: boolean;
  host_account_id: string;
  my_account_id: string;
  my_commander_id: string | null;
  is_host: boolean;
  members: AutoChessRoomMember[];
  invite_urls: string[];
  updated_at: number;
  match: AutoChessMatchState | null;
}
