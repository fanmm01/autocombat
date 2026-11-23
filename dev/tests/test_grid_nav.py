import unittest

import arena_presets as ap
import grid_nav as gn


class GridNavTests(unittest.TestCase):
    def test_coord_roundtrip_and_chebyshev_distance(self):
        for coord in ('A1', 'C4', 'J7', 'L8', 'P16'):
            xy = gn.parse_coord(coord)
            self.assertIsNotNone(xy)
            self.assertEqual(gn.format_coord(*xy), coord)
        self.assertEqual(gn.grid_dist('A1', 'D4'), 3)
        self.assertEqual(gn.grid_dist('E5', 'E5'), 0)

    def test_arena_presets_strict_mirror_symmetry(self):
        for preset_id in ('autochess_standard', 'autochess_compact', 'autochess_citadel', 'classic_open'):
            md = ap.build_arena_map(preset_id)
            w, h = md['width'], md['height']
            y_cols = sorted(md['deploy_cols']['Y'])
            x_cols = sorted(md['deploy_cols']['X'])
            self.assertEqual(len(y_cols), len(x_cols))
            self.assertEqual([w - 1 - c for c in reversed(y_cols)], x_cols)
            for coord, t in md['terrain'].items():
                col, row = gn.parse_coord(coord)
                mcoord = gn.format_coord(w - 1 - col, row)
                self.assertEqual(md['terrain'].get(mcoord), t, f'{preset_id} terrain asymmetry at {coord}')
                if t == 'wall':
                    self.assertFalse(ap.is_in_deploy_zone(md, 'Y', coord))
                    self.assertFalse(ap.is_in_deploy_zone(md, 'X', coord))

    def test_ground_vs_flying_cover_walls_and_corner_squeeze(self):
        md = {
            'width': 6,
            'height': 5,
            'terrain': {'C2': 'wall', 'D3': 'wall', 'B2': 'cover'},
            'occupants': {'A2': 'u_me', 'B3': 'u_ally', 'C3': 'u_enemy'},
        }
        # Cannot enter wall or stop on occupied ally/enemy; cover costs 2 for ground
        nav_ground = gn.compute_navigation(
            md, 'A2', max_cost=2, flying=False, team='Y',
            unit_teams={'u_me': 'Y', 'u_ally': 'Y', 'u_enemy': 'X'},
            ignore_uids={'u_me'},
        )
        reach = nav_ground['reachable']
        self.assertNotIn('C2', reach)
        self.assertNotIn('B3', reach)
        self.assertNotIn('C3', reach)
        self.assertIn('B2', reach)
        self.assertEqual(reach['B2'][0], 2)

        # Wall corner diagonal squeeze blocked for ground, allowed cleanly by flying
        md_corner = {
            'width': 5,
            'height': 5,
            'terrain': {'B1': 'wall', 'A2': 'wall'},
            'occupants': {'A1': 'u_me'},
        }
        nav_squeeze = gn.compute_navigation(md_corner, 'A1', max_cost=1, flying=False, ignore_uids={'u_me'})
        self.assertNotIn('B2', nav_squeeze['reachable'])

        nav_fly = gn.compute_navigation(md_corner, 'A1', max_cost=2, flying=True, ignore_uids={'u_me'})
        self.assertIn('B2', nav_fly['reachable'])
        self.assertIn('C2', nav_fly['reachable'])

    def test_2x2_footprint_displacement_and_attack_pos(self):
        md = ap.build_arena_map('autochess_citadel')
        md['occupants'] = {'B3': 'me', 'I3': 'target'}
        # 2x2 invalid near right edge
        self.assertFalse(gn.is_footprint_valid(md, 'L4', size=2))
        self.assertTrue(gn.is_footprint_valid(md, 'B4', size=2, ignore_uids={'me'}))

        # Unreachable target when budget=0
        reached, dest, cost, _ = gn.find_attack_position(
            md, 'B3', 'I3', atk_range=2, max_cost=0, ignore_uids={'me'},
        )
        self.assertFalse(reached)
        self.assertEqual(dest, 'B3')
        self.assertEqual(cost, 0)

        # Displacement stops cleanly before wall at E3
        pushed = gn.compute_displacement(md, 'C3', 'B3', 4, ignore_uids={'me'})
        self.assertTrue(pushed)
        self.assertEqual(pushed[-1], 'D3')


if __name__ == '__main__':
    unittest.main()
