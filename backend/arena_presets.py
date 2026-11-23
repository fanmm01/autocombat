"""Symmetric battlefield presets, deploy zones, and terrain metadata for Auto-Chess."""
import copy
import math

from grid_nav import parse_coord

ARENA_PRESETS = {
    'autochess_standard': {
        'id': 'autochess_standard',
        'name': '星序标准盘 (10×7)',
        'description': '标准 4 列交战纵深，中场双侧星晶掩体提供远程减伤与走位支点。',
        'width': 10,
        'height': 7,
        'deploy_cols': {
            'Y': [0, 1, 2],
            'X': [7, 8, 9],
        },
        'terrain': {
            'D3': 'cover', 'D5': 'cover',
            'G3': 'cover', 'G5': 'cover',
        },
    },
    'autochess_compact': {
        'id': 'autochess_compact',
        'name': '近战演武盘 (8×6)',
        'description': '紧凑 2 列交战纵深，接战更快、适合快节奏对冲与突进阵容。',
        'width': 8,
        'height': 6,
        'deploy_cols': {
            'Y': [0, 1, 2],
            'X': [5, 6, 7],
        },
        'terrain': {
            'D2': 'cover', 'D5': 'cover',
            'E2': 'cover', 'E5': 'cover',
        },
    },
    'autochess_citadel': {
        'id': 'autochess_citadel',
        'name': '双柱要塞盘 (12×8)',
        'description': '双星柱阻隔与侧翼通道并存，中央 4 格魔能节点提供轮首回蓝争夺。',
        'width': 12,
        'height': 8,
        'deploy_cols': {
            'Y': [0, 1, 2, 3],
            'X': [8, 9, 10, 11],
        },
        'terrain': {
            'E3': 'wall', 'E6': 'wall',
            'H3': 'wall', 'H6': 'wall',
            'F2': 'cover', 'G2': 'cover',
            'F7': 'cover', 'G7': 'cover',
            'F4': 'leyline', 'G4': 'leyline',
            'F5': 'leyline', 'G5': 'leyline',
        },
    },
    'classic_open': {
        'id': 'classic_open',
        'name': '经典开阔场 (10×10)',
        'description': '无地形纯开阔场地，适合无遮挡阵型对照与经典尺寸体验。',
        'width': 10,
        'height': 10,
        'deploy_cols': {
            'Y': [0, 1, 2],
            'X': [7, 8, 9],
        },
        'terrain': {},
    },
}

TERRAIN_DESCRIPTIONS = {
    'wall': '星柱障碍：阻挡地面单位通行与召唤落点；飞行单位可飞越但不可停留。',
    'cover': '星晶掩体：地面单位进入消耗 2 点移动力；受距离 ≥3 格的远程攻击时伤害 -15%。',
    'leyline': '魔能节点：轮首停留其上的存活单位额外回复 +1 MP（不超过上限）。',
}


def get_arena_preset(preset_id='autochess_standard'):
    """Return a copy of the requested preset dict, falling back to standard."""
    key = preset_id if preset_id in ARENA_PRESETS else 'autochess_standard'
    return copy.deepcopy(ARENA_PRESETS[key])


def build_arena_map(preset_id='autochess_standard'):
    """Build a battle map dict compatible with CombatEngine and grid_nav."""
    preset = get_arena_preset(preset_id)
    w = preset['width']
    h = preset['height']
    terrain = dict(preset['terrain'])
    obstacles = {coord: True for coord, kind in terrain.items() if kind == 'wall'}
    return {
        'width': w,
        'height': h,
        'entryRow': math.ceil(h / 2),
        'preset': preset['id'],
        'preset_name': preset['name'],
        'obstacles': obstacles,
        'terrain': terrain,
        'deploy_cols': copy.deepcopy(preset['deploy_cols']),
        'occupants': {},
    }


def is_in_deploy_zone(map_data, team, coord):
    """Return True if coord is inside team's legal deployment columns and passable."""
    if not map_data or not coord:
        return False
    pt = parse_coord(coord)
    if not pt:
        return False
    col, row = pt
    w = int(map_data.get('width', 0) or 0)
    h = int(map_data.get('height', 0) or 0)
    if not (0 <= col < w and 0 <= row < h):
        return False
    terrain = map_data.get('terrain') or {}
    if terrain.get(coord) == 'wall' or (map_data.get('obstacles') or {}).get(coord):
        return False
    deploy_cols = (map_data.get('deploy_cols') or {}).get(team)
    if not deploy_cols:
        if team == 'Y':
            return col < max(1, w // 3)
        return col >= w - max(1, w // 3)
    return col in deploy_cols


def row_band(map_data, team, coord):
    """Classify a deployment coord into 'front' | 'mid' | 'back' relative to team."""
    pt = parse_coord(coord)
    if not pt or not map_data:
        return 'mid'
    col = pt[0]
    w = int(map_data.get('width', 10) or 10)
    deploy_cols = sorted((map_data.get('deploy_cols') or {}).get(team) or (
        list(range(max(1, w // 3))) if team == 'Y' else list(range(w - max(1, w // 3), w))
    ))
    if not deploy_cols or col not in deploy_cols:
        return 'mid'
    idx = deploy_cols.index(col)
    if team == 'X':
        idx = len(deploy_cols) - 1 - idx
    if idx == len(deploy_cols) - 1:
        return 'front'
    if idx == 0:
        return 'back'
    return 'mid'
