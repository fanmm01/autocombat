"""Grid geometry, terrain queries, and BFS/Dijkstra pathfinding for autocombat.

Kept dependency-free (stdlib only) so scripts/merge_backend.py can inline it
ahead of battle_engine.py without circular dependencies.
"""
import heapq
import re


def parse_coord(s):
    """Parse board coordinate like 'A1' -> (col, row) 0-indexed tuple, or None."""
    if not isinstance(s, str):
        return None
    m = re.match(r'^([A-Z])(\d+)$', s.strip().upper())
    return (ord(m.group(1)) - 65, int(m.group(2)) - 1) if m else None


def format_coord(col, row):
    """Format 0-indexed (col, row) into 'A1' coordinate string."""
    if col < 0 or col >= 26 or row < 0:
        return ''
    return f'{chr(65 + col)}{row + 1}'


def _to_xy(coord_or_xy):
    if isinstance(coord_or_xy, tuple) and len(coord_or_xy) == 2:
        return coord_or_xy
    return parse_coord(coord_or_xy)


def grid_dist(a, b):
    """Canonical 8-way Chebyshev distance between two coords or (col, row) tuples."""
    ap = _to_xy(a)
    bp = _to_xy(b)
    if not ap or not bp:
        return 999
    return max(abs(ap[0] - bp[0]), abs(ap[1] - bp[1]))


def footprint_cells(anchor, size=1):
    """Return 0-indexed (col, row) cells covered by a unit footprint at anchor."""
    xy = _to_xy(anchor)
    if not xy:
        return []
    c, r = xy
    if size <= 1:
        return [(c, r)]
    return [(c + dc, r + dr) for dc in range(size) for dr in range(size)]


def terrain_type(map_data, coord):
    """Return terrain type at coord: 'wall' | 'cover' | 'leyline' | ''."""
    if not map_data or not coord:
        return ''
    t = (map_data.get('terrain') or {}).get(coord, '')
    if t:
        return t
    if (map_data.get('obstacles') or {}).get(coord):
        return 'wall'
    return ''


def tile_enter_cost(map_data, coord, *, flying=False):
    """Movement cost to step onto coord (ground units pay 2 on 'cover')."""
    if flying:
        return 1
    return 2 if terrain_type(map_data, coord) == 'cover' else 1


def _occupant_map(map_data):
    return (map_data or {}).get('occupants') or {}


def _is_landing_valid(map_data, xy, *, size=1, ignore_uids=()):
    """True if all footprint cells are in bounds, non-wall, and unoccupied."""
    if not map_data or not xy:
        return False
    w = int(map_data.get('width', 0) or 0)
    h = int(map_data.get('height', 0) or 0)
    if w <= 0 or h <= 0:
        return False
    occs = _occupant_map(map_data)
    ignored = set(ignore_uids or ())
    for c, r in footprint_cells(xy, size):
        if not (0 <= c < w and 0 <= r < h):
            return False
        coord = format_coord(c, r)
        if not coord or terrain_type(map_data, coord) == 'wall':
            return False
        occ = occs.get(coord)
        if occ and occ not in ignored:
            return False
    return True


def _is_pass_valid(map_data, xy, *, size=1, flying=False, team='Y',
                   unit_teams=None, ignore_uids=()):
    """True if unit can traverse xy during movement (friends passable on ground)."""
    if not map_data or not xy:
        return False
    w = int(map_data.get('width', 0) or 0)
    h = int(map_data.get('height', 0) or 0)
    if w <= 0 or h <= 0:
        return False
    occs = _occupant_map(map_data)
    ignored = set(ignore_uids or ())
    for c, r in footprint_cells(xy, size):
        if not (0 <= c < w and 0 <= r < h):
            return False
        coord = format_coord(c, r)
        if not coord:
            return False
        if flying:
            continue
        if terrain_type(map_data, coord) == 'wall':
            return False
        occ = occs.get(coord)
        if occ and occ not in ignored:
            if unit_teams is None:
                return False
            occ_team = unit_teams.get(occ)
            if occ_team is not None and occ_team != team:
                return False
    return True


def is_footprint_valid(map_data, anchor, *, size=1, flying=False, ignore_uids=()):
    """Public check whether anchor can legally hold a unit of given size."""
    xy = _to_xy(anchor)
    return _is_landing_valid(map_data, xy, size=size, ignore_uids=ignore_uids)


def reconstruct_path(parents, start_coord, dest_coord):
    """Rebuild [start_coord, ..., dest_coord] from a parent dict."""
    if not start_coord or not dest_coord:
        return []
    if dest_coord == start_coord:
        return [start_coord]
    if dest_coord not in parents:
        return []
    path = []
    cur = dest_coord
    seen = set()
    while cur is not None:
        if cur in seen:
            return []
        seen.add(cur)
        path.append(cur)
        if cur == start_coord:
            break
        cur = parents.get(cur)
    if not path or path[-1] != start_coord:
        return []
    path.reverse()
    return path


_NEIGHBORS_8 = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)


def compute_navigation(map_data, start_coord, max_cost, *, flying=False, team='Y',
                       unit_teams=None, ignore_uids=(), size=1):
    """Run bounded Dijkstra from start_coord.

    Returns dict:
        reachable: {coord: (cost, prev_coord)} for valid LANDING cells (incl. start)
        parents: {coord: prev_coord} for all traversed cells
        costs: {coord: min_cost}
    """
    start_xy = _to_xy(start_coord)
    if not map_data or not start_xy or max_cost < 0:
        return {'reachable': {}, 'parents': {}, 'costs': {}}
    start_str = format_coord(*start_xy)
    w = int(map_data.get('width', 0) or 0)
    h = int(map_data.get('height', 0) or 0)
    if not (0 <= start_xy[0] < w and 0 <= start_xy[1] < h):
        return {'reachable': {}, 'parents': {}, 'costs': {}}

    costs = {start_str: 0}
    parents = {start_str: None}
    reachable = {start_str: (0, None)}
    # Tie-breaker prefers orthogonal steps slightly (fewer diagonal zigzags)
    heap = [(0, 0, start_xy[0], start_xy[1], start_str)]
    seq = 0
    while heap:
        cur_cost, _, cx, cy, ccoord = heapq.heappop(heap)
        if cur_cost > costs.get(ccoord, 10**9):
            continue
        if cur_cost >= max_cost:
            continue
        for dc, dr in _NEIGHBORS_8:
            nx, ny = cx + dc, cy + dr
            ncoord = format_coord(nx, ny)
            if not ncoord:
                continue
            if not flying and size == 1 and dc != 0 and dr != 0:
                # Prevent squeezing diagonally through two touching wall corners.
                c1 = format_coord(cx + dc, cy)
                c2 = format_coord(cx, cy + dr)
                if terrain_type(map_data, c1) == 'wall' and terrain_type(map_data, c2) == 'wall':
                    continue
            if not _is_pass_valid(map_data, (nx, ny), size=size, flying=flying,
                                  team=team, unit_teams=unit_teams,
                                  ignore_uids=ignore_uids):
                continue
            step_cost = max(
                tile_enter_cost(map_data, format_coord(fx, fy), flying=flying)
                for fx, fy in footprint_cells((nx, ny), size)
            )
            new_cost = cur_cost + step_cost
            if new_cost > max_cost:
                continue
            old_cost = costs.get(ncoord)
            if old_cost is None or new_cost < old_cost:
                costs[ncoord] = new_cost
                parents[ncoord] = ccoord
                seq += 1
                diag_tie = 1 if (dc != 0 and dr != 0) else 0
                heapq.heappush(heap, (new_cost, diag_tie * 100000 + seq, nx, ny, ncoord))
                if _is_landing_valid(map_data, (nx, ny), size=size, ignore_uids=ignore_uids):
                    reachable[ncoord] = (new_cost, ccoord)

    return {'reachable': reachable, 'parents': parents, 'costs': costs}


def reachable_cells(map_data, start_coord, max_cost, *, flying=False, team='Y',
                    unit_teams=None, ignore_uids=(), size=1):
    """Return {coord: (cost, prev_coord)} for all legal stopping tiles."""
    return compute_navigation(
        map_data, start_coord, max_cost,
        flying=flying, team=team, unit_teams=unit_teams,
        ignore_uids=ignore_uids, size=size,
    )['reachable']


def find_attack_position(map_data, start_coord, target_coord, atk_range, max_cost, *,
                         flying=False, team='Y', unit_teams=None, ignore_uids=(),
                         size=1, hazard_coords=None, preferred_coords=None):
    """Find best legal destination to attack target_coord within atk_range.

    Returns (reached: bool, dest_coord: str, move_cost: int, path: list[str]).
    When target cannot be reached within max_cost, returns (False, closest_coord, ...)
    without falsely reporting reached=True or overshooting through walls.
    """
    start_xy = _to_xy(start_coord)
    target_xy = _to_xy(target_coord)
    if not start_xy or not target_xy or not map_data:
        return (False, start_coord or '', 0, [])
    start_str = format_coord(*start_xy)
    target_str = format_coord(*target_xy)
    cur_dist = grid_dist(start_xy, target_xy)
    if cur_dist <= atk_range:
        return (True, start_str, 0, [start_str])
    if max_cost <= 0:
        return (False, start_str, 0, [start_str])

    nav = compute_navigation(
        map_data, start_str, max_cost,
        flying=flying, team=team, unit_teams=unit_teams,
        ignore_uids=ignore_uids, size=size,
    )
    reachable = nav['reachable']
    parents = nav['parents']
    hazards = set(hazard_coords or ())
    preferred = set(preferred_coords or ())

    in_range = [
        (coord, meta[0]) for coord, meta in reachable.items()
        if coord != start_str and grid_dist(coord, target_str) <= atk_range
    ]
    if in_range:
        def _atk_key(item):
            coord, cost = item
            d = grid_dist(coord, target_str)
            # Ranged units prefer max safe distance in range; melee prefers cheapest/closest
            range_tie = -d if atk_range >= 4 else d
            return (
                cost,
                1 if coord in hazards else 0,
                0 if coord in preferred else 1,
                range_tie,
                coord,
            )
        best_coord, best_cost = min(in_range, key=_atk_key)
        return (True, best_coord, best_cost, reconstruct_path(parents, start_str, best_coord))

    # Could not enter range this turn — advance to closest legal tile if strictly closer
    closer = [
        (coord, meta[0], grid_dist(coord, target_str))
        for coord, meta in reachable.items()
        if coord != start_str and grid_dist(coord, target_str) < cur_dist
    ]
    if closer:
        best_coord, best_cost, _ = min(
            closer,
            key=lambda it: (it[2], 1 if it[0] in hazards else 0, 0 if it[0] in preferred else 1, it[1], it[0]),
        )
        return (False, best_coord, best_cost, reconstruct_path(parents, start_str, best_coord))

    return (False, start_str, 0, [start_str])


def find_free_coord_near(map_data, origin_coord, *, size=1, max_radius=12):
    """Find closest valid landing cell within map bounds around origin_coord."""
    if not map_data:
        return None
    origin_xy = _to_xy(origin_coord) or (1, 1)
    w = int(map_data.get('width', 0) or 0)
    h = int(map_data.get('height', 0) or 0)
    limit = max(max_radius, max(w, h))
    for radius in range(0, limit + 1):
        candidates = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                nx, ny = origin_xy[0] + dx, origin_xy[1] + dy
                if _is_landing_valid(map_data, (nx, ny), size=size):
                    candidates.append((abs(dx) + abs(dy), nx, ny))
        if candidates:
            _, bx, by = min(candidates)
            return format_coord(bx, by)
    return None


def compute_displacement(map_data, start_coord, ref_coord, steps, kind='push',
                         *, flying=False, ignore_uids=()):
    """Compute step-by-step push/pull displacement path stopping cleanly at blocks."""
    start_xy = _to_xy(start_coord)
    ref_xy = _to_xy(ref_coord)
    if not map_data or not start_xy or not ref_xy or steps <= 0:
        return []
    dx = (start_xy[0] > ref_xy[0]) - (start_xy[0] < ref_xy[0])
    dy = (start_xy[1] > ref_xy[1]) - (start_xy[1] < ref_xy[1])
    if kind == 'pull':
        dx, dy = -dx, -dy
    if dx == 0 and dy == 0:
        return []
    cx, cy = start_xy
    path = []
    for _ in range(steps):
        nx, ny = cx + dx, cy + dy
        ncoord = format_coord(nx, ny)
        if not ncoord:
            break
        if kind == 'pull' and (nx, ny) == ref_xy:
            break
        if not _is_landing_valid(map_data, (nx, ny), size=1, ignore_uids=ignore_uids):
            break
        path.append(ncoord)
        cx, cy = nx, ny
    return path
