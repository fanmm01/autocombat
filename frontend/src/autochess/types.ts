export interface AutoChessUnitMeta {
  serial: string;
  name: string;
  cost: number;
  role: 'tank' | 'bruiser' | 'assassin' | 'ranged' | 'support' | 'summoner' | string;
  traits: string[];
  range: number;
  tag: string;
  blurb: string;
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
  is_human: boolean;
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

export interface AutoChessCombatFrame {
  round: number;
  actor_uid: string | null;
  actor_name: string;
  team: 'Y' | 'X';
  cmd: string;
  reason: string;
  lines: string[];
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
  id: string;
  mode: 'lobby4' | 'pve12';
  arena_preset: string;
  arena_name: string;
  round_num: number;
  prep_deadline?: number;
  max_waves: number | null;
  phase: 'prep' | 'combat' | 'round_result' | 'finished';
  winner_id: string | null;
  map: {
    width: number;
    height: number;
    deploy_cols: Record<string, number[]>;
    terrain: Record<string, 'wall' | 'cover' | 'leyline'>;
  };
  player: {
    id: string;
    name: string;
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
  id: string;
  mode: 'lobby4' | 'pve12';
  arena_preset: string;
  round_num: number;
  phase: string;
  hp: number;
  updated_at: number;
}

export interface AutoChessCatalog {
  units: AutoChessUnitMeta[];
  synergies: AutoChessSynergyDef[];
  augments: AutoChessAugment[];
  arenas: AutoChessArenaPreset[];
  terrains: Record<string, { name: string; summary: string }>;
  levels: Record<string, { max_pop: number; xp_to_next: number; odds: Record<string, number> }>;
  pool_counts: Record<string, number>;
}
