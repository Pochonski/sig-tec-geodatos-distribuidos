"""Regresión: no confundir los IDs cortos y completos de Docker."""
import json
import unittest
from unittest.mock import patch

import wal


class InventoryTests(unittest.TestCase):
    def test_excludes_only_target_containers_with_short_ids(self):
        target = 'a' * 64
        other = 'b' * 64
        with patch.object(wal, 'run', return_value=json.dumps([{'Id': target}])), \
                patch.object(wal, 'inventory', return_value={target: ['target'], other: ['other']}):
            self.assertEqual(wal.other_inventory({'central': target[:12]}), {other: ['other']})


if __name__ == '__main__':
    unittest.main(verbosity=2)
