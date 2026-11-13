"""Integración real contra sig-tec-ops; conserva fixtures y evidencias propias."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from uuid import uuid4

import psycopg

import rename
from verify import inventory

ROOT = Path(__file__).resolve().parent
EVIDENCE = []


class RenameIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = rename.configuration()
        cls.before = inventory()

    @classmethod
    def tearDownClass(cls):
        if inventory() != cls.before:
            raise AssertionError('Cambió el estado o montaje de un contenedor')

    def setUp(self):
        self.operation = uuid4()
        # BIGINT positivo con la clase de Cartago (1 módulo 5).
        self.building = (uuid4().int % 10**14) * 5 + 1
        self.name = f"Prueba 2PC - {self.operation} - 'Cartago' ñ"
        node = rename.CAMPUSES[1]
        with psycopg.connect(host='127.0.0.1', port=node.port, dbname='sig_tec',
                             user='postgres', password=self.values['OPS_CARTAGO_PASSWORD']) as admin:
            admin.execute('INSERT INTO cartago.edificios (id, campus_id, nombre) '
                          'VALUES (%s, 1, %s)', (self.building, 'Fixture CLI 2PC'))

    def cli(self, name=None, building=None):
        proc = subprocess.run([
            sys.executable, '-B', str(ROOT / 'rename.py'), str(self.operation), '1',
            str(self.building if building is None else building),
            self.name if name is None else name,
        ], text=True, capture_output=True, timeout=40)
        # Evitar que errores impriman configuración de conexiones o secretos.
        self.assertEqual(proc.stderr, '')
        return proc.returncode, json.loads(proc.stdout)

    def state(self):
        result = []
        with rename.connect(rename.CENTRAL, self.values) as central:
            for table in ('requests', 'decisions', 'audit'):
                result.append(central.execute(
                    psycopg.sql.SQL('SELECT * FROM ops.{} WHERE operation_id = %s').format(
                        psycopg.sql.Identifier(table)), (self.operation,),
                ).fetchall())
        with rename.connect(rename.CAMPUSES[1], self.values) as campus:
            result.append(campus.execute('SELECT * FROM ops.applied_operations '
                                         'WHERE operation_id = %s', (self.operation,)).fetchall())
            result.append(campus.execute('SELECT id, campus_id, nombre FROM cartago.edificios '
                                         'WHERE id = %s', (self.building,)).fetchall())
        return result

    def verify_success(self):
        requests, decisions, audit, applied, buildings = self.state()
        for rows in (requests, decisions, audit, applied, buildings):
            self.assertEqual(len(rows), 1)
        self.assertEqual(requests[0][1:4], (1, self.building, self.name))
        self.assertEqual(decisions[0][1], 'COMMIT')
        self.assertEqual(audit[0][1:4], (1, self.building, self.name))
        self.assertEqual(applied[0][1:4], (1, self.building, self.name))
        self.assertEqual(buildings, [(self.building, 1, self.name)])
        for node in (rename.CENTRAL, rename.CAMPUSES[1]):
            with rename.connect(node, self.values) as conn:
                self.assertFalse(rename.prepared(conn, self.operation, node))
        EVIDENCE.append({'test': self._testMethodName, 'operation_id': str(self.operation),
                         'building_id': self.building, 'name': self.name,
                         'decision': 'COMMIT', 'audit_rows': 1, 'campus_markers': 1,
                         'prepared_transactions': 0})

    def test_success(self):
        code, result = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['repeated'])
        self.verify_success()

    def test_identical_retry(self):
        self.assertEqual(self.cli()[0], 0)
        before = self.state()
        code, result = self.cli()
        self.assertEqual(code, 0)
        self.assertTrue(result['repeated'])
        self.assertEqual(self.state(), before)  # Incluye timestamps de todos los registros.
        self.verify_success()

    def test_uuid_reused_with_different_data(self):
        self.assertEqual(self.cli()[0], 0)
        before = self.state()
        for changes in ({'name': 'Otro nombre'}, {'building': self.building + 5}):
            code, result = self.cli(**changes)
            self.assertEqual(code, 1)
            self.assertEqual(result['status'], 'error')
            self.assertIn('UUID reutilizado', result['message'])
            self.assertEqual(self.state(), before)
        self.verify_success()

    def test_concurrent_identical_uuid(self):
        with rename.connect(rename.CENTRAL, self.values) as gate:
            key = rename.lock_key(self.operation)
            gate.execute('SELECT pg_advisory_lock(%s)', (key,))
            with ThreadPoolExecutor(max_workers=2) as workers:
                jobs = [workers.submit(self.cli) for _ in range(2)]
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        waiting = gate.execute(
                            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                            "AND NOT granted AND pid IN (SELECT pid FROM pg_stat_activity "
                            "WHERE application_name = 'sig-tec-ops-rename')"
                        ).fetchone()[0]
                        if waiting >= 2:
                            break
                        time.sleep(0.05)
                    self.assertGreaterEqual(waiting, 2, 'Ambos procesos deben esperar el bloqueo')
                finally:
                    gate.execute('SELECT pg_advisory_unlock(%s)', (key,))
                results = [job.result() for job in jobs]
        self.assertEqual([code for code, _ in results], [0, 0])
        self.assertEqual(sorted(result['repeated'] for _, result in results), [False, True])
        self.verify_success()


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RenameIntegration)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        (ROOT / 'test-results.json').write_text(json.dumps(EVIDENCE, ensure_ascii=False, indent=2) + '\n')
        print('Evidencia sin credenciales: ops/test-results.json')
    sys.exit(0 if result.wasSuccessful() else 1)
