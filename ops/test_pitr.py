"""Pruebas de aislamiento y una recuperación PITR real de Cartago."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backup
import pitr
import wal
from verify import inventory

ROOT = Path(__file__).resolve().parent


class PITRSafety(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'pitr-unit-data'
        scratch.mkdir(mode=0o700, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'backups' / 'data'
        self.source.mkdir(parents=True)
        (self.source / 'PG_VERSION').write_text('17\n', encoding='utf-8')
        (self.source / 'postgresql.auto.conf').write_text('# Original intacto\n', encoding='utf-8')
        self.runs = self.root / 'runs'
        self.runs.mkdir()
        self.point = 'sig_tec_pitr_' + 'a' * 32

    def test_wal_range_including_log_number_rollover(self):
        self.assertEqual(pitr.required_segments('0/FF000000', '1/1000000', 1, 16 * 2**20),
                         ['0000000100000000000000FF', '000000010000000100000000'])
        with self.assertRaises(pitr.PITRError):
            pitr.required_segments('0/100', '0/100', 1, 16 * 2**20)

    def test_only_new_copy_receives_recovery_configuration(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        with patch.object(backup, 'BACKUPS', self.source.parent), patch.object(pitr, 'RUNS', self.runs):
            dest = pitr.prepare_copy(self.source, self.runs / 'pgdata', self.point)
        self.assertTrue((dest / 'recovery.signal').exists())
        config = (dest / 'postgresql.auto.conf').read_text(encoding='utf-8')
        self.assertIn("recovery_target_action = 'pause'", config)
        self.assertIn("recovery_target_timeline = 'current'", config)
        self.assertIn(self.point, config)
        self.assertIn('archive_mode = off', config)
        self.assertEqual({p.name: p.read_bytes() for p in self.source.iterdir()}, before)

    def test_recovery_keeps_primary_worker_limits_without_starting_subscribers(self):
        with patch.object(backup,'BACKUPS',self.source.parent), patch.object(pitr,'RUNS',self.runs):
            destination=pitr.prepare_copy(self.source,self.runs/'pgdata',self.point,{'max_worker_processes':'48','max_wal_senders':'32'})
        config=(destination/'postgresql.auto.conf').read_text(encoding='utf-8')
        self.assertIn('max_worker_processes = 48',config)
        self.assertIn('max_wal_senders = 32',config)
        self.assertIn('max_logical_replication_workers = 0',config)

    def test_reject_existing_or_external_destinations(self):
        with patch.object(backup, 'BACKUPS', self.source.parent), patch.object(pitr, 'RUNS', self.runs):
            for destination in (self.source, self.runs, self.root / 'outside'):
                with self.assertRaises(pitr.PITRError):
                    pitr.prepare_copy(self.source, destination, self.point)

    def test_reject_target_injection(self):
        with self.assertRaises(pitr.PITRError):
            pitr.prepare_copy(self.source, self.runs / 'pgdata', "name'\narchive_mode=on")


class PITRIntegration(unittest.TestCase):
    def test_real_named_point_recovery_and_preservation(self):
        containers_before = inventory()
        result = pitr.exercise()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['target_reached']['paused']['in_recovery'])
        self.assertEqual(result['target_reached']['paused']['state'], 'paused')
        self.assertFalse(result['recovery_finished']['state']['in_recovery'])
        self.assertEqual(result['recovery_finished']['restored_fixture'], result['fixture'])
        self.assertTrue(result['recovery_finished']['all_table_hashes_match'])
        self.assertTrue(result['temporary_container_removed'])
        with backup.admin('cartago', wal.configuration()) as conn:
            self.assertIsNone(conn.execute('SELECT id FROM cartago.edificios WHERE id=%s',
                                           (result['fixture']['id'],)).fetchone())
        self.assertEqual(inventory(), containers_before)
        evidence = json.loads(pitr.REPORT.read_text(encoding='utf-8'))
        evidence['automated_tests'] = {'command': 'ops/.venv/bin/python -B ops/test_pitr.py',
                                      'unit_safety_tests': 5, 'real_pitr_tests': 1, 'result': 'passed'}
        backup.save(pitr.REPORT, evidence)


if __name__ == '__main__':
    # Validar primero los guardas; no escribir fixtures reales si fallan.
    runner = unittest.TextTestRunner(verbosity=2)
    safety = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(PITRSafety))
    if not safety.wasSuccessful():
        raise SystemExit(1)
    integration = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(PITRIntegration))
    raise SystemExit(0 if integration.wasSuccessful() else 1)
