"""Regresión: no confundir los IDs cortos y completos de Docker."""
import json
from collections import namedtuple
import unittest
from unittest.mock import patch

import wal
import verify


class InventoryTests(unittest.TestCase):
    def test_authorized_branches_include_main_and_development(self):
        self.assertTrue(wal.authorized_branch('armando/operaciones'))
        self.assertTrue(wal.authorized_branch('main'))

    def test_preflight_reaches_safety_checks_from_both_authorized_branches(self):
        usage = namedtuple('usage', 'total used free')
        for branch in ('armando/operaciones', 'main'):
            with self.subTest(branch=branch), \
                    patch.object(wal, 'run', return_value=branch), \
                    patch.object(wal.shutil, 'disk_usage', return_value=usage(1, 1, 0)):
                with self.assertRaisesRegex(wal.SafetyError, 'Espacio insuficiente'):
                    wal.preflight()

    def test_other_branches_and_detached_head_are_rejected(self):
        self.assertFalse(wal.authorized_branch('feature/unsafe'))
        self.assertFalse(wal.authorized_branch(''))

    def test_inventory_normalizes_docker_mount_order(self):
        mounts = [
            {'Type': 'volume', 'Name': 'data', 'Source': '/data', 'Destination': '/var/lib/postgresql/data'},
            {'Type': 'bind', 'Source': '/ops', 'Destination': '/ops'},
        ]
        details = [{'Id': 'node', 'State': {'StartedAt': 'now', 'Status': 'running'}, 'Mounts': mounts}]
        with patch.object(verify.subprocess, 'check_output', side_effect=['node', json.dumps(details)]):
            first = verify.inventory()
        details[0]['Mounts'] = list(reversed(mounts))
        with patch.object(verify.subprocess, 'check_output', side_effect=['node', json.dumps(details)]):
            second = verify.inventory()
        self.assertEqual(first, second)

    def test_excludes_only_target_containers_with_short_ids(self):
        target = 'a' * 64
        other = 'b' * 64
        with patch.object(wal, 'run', return_value=json.dumps([{'Id': target}])), \
                patch.object(wal, 'inventory', return_value={target: ['target'], other: ['other']}):
            self.assertEqual(wal.other_inventory({'central': target[:12]}), {other: ['other']})


if __name__ == '__main__':
    unittest.main(verbosity=2)
