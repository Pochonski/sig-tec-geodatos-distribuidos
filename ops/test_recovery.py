"""Fallos 2PC reproducibles; únicamente fixtures nuevos en sig-tec-ops."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql

import recover
import rename
from verify import inventory

ROOT = Path(__file__).resolve().parent
RESULTS = []


def existing_data(values):
    result = {}
    for node, tables in ((rename.CENTRAL, ('ops.requests', 'ops.decisions', 'ops.audit')),
                         (rename.CAMPUSES[1], ('ops.applied_operations', 'cartago.edificios'))):
        with rename.connect(node, values) as conn:
            for table in tables:
                columns = 'id, campus_id, nombre' if table == 'cartago.edificios' else '*'
                rows = conn.execute(sql.SQL('SELECT {} FROM {}').format(
                    sql.SQL(columns), sql.Identifier(*table.split('.')))).fetchall()
                result[table] = {row[0]: row for row in rows}
    return result


class RecoveryIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = rename.configuration()
        cls.before_containers = inventory()
        cls.protected = existing_data(cls.values)
        cls.initial_prepared = cls.prepared_inventory()
        cls.versions = {}
        for node in (rename.CENTRAL, rename.CAMPUSES[1]):
            with rename.connect(node, cls.values) as conn:
                cls.versions[node.name] = conn.execute(
                    "SELECT current_setting('server_version'), public.postgis_lib_version()"
                ).fetchone()

    @classmethod
    def prepared_inventory(cls):
        result = {}
        for node in (rename.CENTRAL, rename.CAMPUSES[1]):
            with rename.connect(node, cls.values) as conn:
                result[node.name] = conn.execute(
                    'SELECT gid, owner, database FROM pg_prepared_xacts ORDER BY gid').fetchall()
        return result

    @classmethod
    def tearDownClass(cls):
        after = existing_data(cls.values)
        for table, protected in cls.protected.items():
            for key, row in protected.items():
                if after[table].get(key) != row:
                    raise AssertionError(f'Se alteró un registro anterior en {table}')
        if inventory() != cls.before_containers:
            raise AssertionError('Cambió el estado o montaje de un contenedor')
        if cls.prepared_inventory() != cls.initial_prepared:
            raise AssertionError('Quedaron transacciones preparadas nuevas')

    def setUp(self):
        self.operation = uuid4()
        self.building = (uuid4().int % 10**14) * 5 + 1
        self.original = f'Fixture recuperación {self.operation}'
        self.name = f"Recuperado Cartago 'ñ' {self.operation}"
        with psycopg.connect(host='127.0.0.1', port=57431, dbname='sig_tec',
                             user='postgres', password=self.values['OPS_CARTAGO_PASSWORD']) as admin:
            admin.execute('INSERT INTO cartago.edificios (id, campus_id, nombre) VALUES (%s, 1, %s)',
                          (self.building, self.original))

    def tearDown(self):
        # Ante una aserción fallida, intentar resolver solo el UUID de esta prueba
        # con la decisión real. Nunca buscar ni modificar operaciones anteriores.
        try:
            recover.recover(self.operation, self.values)
        except rename.OperationError:
            pass

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / script), *map(str, args)],
                              text=True, capture_output=True, timeout=40)

    def crash(self, point):
        proc = self.run_script('fault_worker.py', 'crash', self.operation, self.building, self.name, point)
        self.assertEqual(proc.returncode, 86, proc.stderr)
        self.assertEqual(proc.stdout.strip(), point)
        self.assertEqual(proc.stderr, '')
        # Esperar el cierre de las sesiones del proceso antes de observar las
        # ramas; el bloqueo central también sincroniza recuperación y renombrado.
        with rename.connect(rename.CENTRAL, self.values) as control:
            control.execute('SELECT pg_advisory_lock(%s)', (rename.lock_key(self.operation),))

    def snapshot(self):
        result = {'records': {}, 'prepared': {}}
        for node, tables in ((rename.CENTRAL, ('requests', 'decisions', 'audit')),
                             (rename.CAMPUSES[1], ('applied_operations',))):
            with rename.connect(node, self.values) as conn:
                for table in tables:
                    result['records'][table] = conn.execute(
                        sql.SQL('SELECT * FROM ops.{} WHERE operation_id = %s').format(sql.Identifier(table)),
                        (self.operation,),
                    ).fetchall()
                result['prepared'][node.name] = rename.prepared(conn, self.operation, node)
                if node.name == 'cartago':
                    result['building'] = conn.execute(
                        'SELECT id, campus_id, nombre FROM cartago.edificios WHERE id = %s',
                        (self.building,),
                    ).fetchone()
        return result

    def recovery_cli(self):
        proc = self.run_script('recover.py', self.operation)
        self.assertEqual(proc.stderr, '')
        return proc.returncode, json.loads(proc.stdout)

    def verify_terminal(self, decision, expected_resolved):
        code, result = self.recovery_cli()
        self.assertEqual(code, 0, result)
        self.assertEqual(result['decision'], decision)
        self.assertEqual(set(result['resolved']), set(expected_resolved))
        state = self.snapshot()
        rows = state['records']
        self.assertEqual(len(rows['requests']), 1)
        self.assertEqual(rows['requests'][0][1:4], (1, self.building, self.name))
        self.assertEqual(len(rows['decisions']), 1)
        self.assertEqual(rows['decisions'][0][1], decision)
        self.assertFalse(any(state['prepared'].values()))
        count = 1 if decision == 'COMMIT' else 0
        for table in ('audit', 'applied_operations'):
            self.assertEqual(len(rows[table]), count)
            if count:
                self.assertEqual(rows[table][0][1:4], (1, self.building, self.name))
        self.assertEqual(state['building'],
                         (self.building, 1, self.name if count else self.original))
        # Repetir la recuperación y el comando original: tampoco cambian timestamps.
        repeat_code, repeat = self.recovery_cli()
        self.assertEqual(repeat_code, 0)
        self.assertEqual(repeat['resolved'], [])
        proc = self.run_script('rename.py', self.operation, 1, self.building, self.name)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        retry = json.loads(proc.stdout)
        self.assertEqual(retry['status'], 'completed' if count else 'aborted')
        self.assertTrue(retry['repeated'])
        self.assertEqual(self.snapshot(), state)
        RESULTS.append({'scenario': self._testMethodName, 'operation_id': str(self.operation),
                        'building_id': self.building, 'decision': decision,
                        'resolved': result['resolved'], 'audit_rows': count,
                        'campus_markers': count, 'prepared_transactions': 0,
                        'name': state['building'][2], 'retries_unchanged': True})

    def test_after_first_prepare(self):
        self.crash('after_first_prepare')
        state = self.snapshot()
        self.assertEqual(state['prepared'], {'central': False, 'cartago': True})
        self.assertEqual(state['records']['decisions'], [])
        self.verify_terminal('ABORT', ['cartago'])

    def test_after_both_prepare_before_decision(self):
        self.crash('after_both_prepare')
        state = self.snapshot()
        self.assertTrue(all(state['prepared'].values()))
        self.assertEqual(state['records']['decisions'], [])
        self.verify_terminal('ABORT', ['cartago', 'central'])

    def test_after_commit_decision(self):
        self.crash('after_decision')
        state = self.snapshot()
        self.assertTrue(all(state['prepared'].values()))
        self.assertEqual(state['records']['decisions'][0][1], 'COMMIT')
        self.verify_terminal('COMMIT', ['cartago', 'central'])

    def test_after_only_one_commit(self):
        self.crash('after_first_commit')
        state = self.snapshot()
        self.assertEqual(state['prepared'], {'central': True, 'cartago': False})
        self.assertEqual(len(state['records']['applied_operations']), 1)
        self.assertEqual(state['records']['audit'], [])
        self.verify_terminal('COMMIT', ['central'])

    def offline_then_recover(self, checkpoint, decision):
        self.crash(checkpoint)
        before = self.snapshot()
        # Puerto reservado, sin listen(): rechaza TCP únicamente para el worker.
        # El central real sigue disponible para otros usuarios y contenedores.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            proc = self.run_script('fault_worker.py', 'offline', self.operation,
                                   unavailable.getsockname()[1])
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr, '')
        self.assertEqual(json.loads(proc.stdout)['status'], 'pending')
        self.assertEqual(self.snapshot(), before)
        self.verify_terminal(decision, ['cartago', 'central'])

    def test_central_inaccessible_without_decision(self):
        self.offline_then_recover('after_both_prepare', 'ABORT')

    def test_central_inaccessible_with_commit(self):
        self.offline_then_recover('after_decision', 'COMMIT')

    def test_uncertain_abort_acknowledgement(self):
        self.crash('after_both_prepare')
        original_connect = rename.connect

        class LostAcknowledgement:
            def __init__(self, conn):
                self.conn = conn

            def close(self):
                self.conn.close()

            def execute(self, statement, *args, **kwargs):
                result = self.conn.execute(statement, *args, **kwargs)
                if isinstance(statement, str) and 'INSERT INTO ops.decisions' in statement:
                    # Persistir ABORT realmente, pero ocultar su confirmación
                    # al código bajo prueba como si se perdiera la respuesta.
                    raise psycopg.OperationalError('Confirmación perdida (inyección de prueba)')
                return result

        def connect(node, values):
            conn = original_connect(node, values)
            return LostAcknowledgement(conn) if node == rename.CENTRAL else conn

        with patch.object(rename, 'connect', side_effect=connect):
            with self.assertRaises(rename.Pending):
                recover.recover(self.operation, self.values)
        state = self.snapshot()
        self.assertTrue(all(state['prepared'].values()))
        self.assertEqual(state['records']['decisions'][0][1], 'ABORT')
        self.assertEqual(state['building'][2], self.original)
        self.verify_terminal('ABORT', ['cartago', 'central'])

    def test_missing_branch_requires_reconciliation(self):
        self.crash('after_decision')
        before = self.snapshot()
        real_evidence = recover.evidence

        def missing_branch(*args):
            observed = real_evidence(*args)
            # No destruir una rama con COMMIT duradero para fabricar corrupción.
            # Se simula solo la lectura que devolvería una rama perdida.
            observed['central']['prepared'] = False
            return observed

        with patch.object(recover, 'evidence', side_effect=missing_branch):
            with self.assertRaisesRegex(rename.Pending, 'reconciliación pendiente'):
                recover.recover(self.operation, self.values)
        self.assertEqual(self.snapshot(), before)
        self.verify_terminal('COMMIT', ['cartago', 'central'])

    def test_concurrent_recovery(self):
        self.crash('after_decision')
        with rename.connect(rename.CENTRAL, self.values) as gate:
            key = rename.lock_key(self.operation)
            gate.execute('SELECT pg_advisory_lock(%s)', (key,))
            with ThreadPoolExecutor(max_workers=2) as workers:
                jobs = [workers.submit(self.recovery_cli) for _ in range(2)]
                try:
                    deadline = time.monotonic() + 5
                    waiting = 0
                    while time.monotonic() < deadline:
                        waiting = gate.execute(
                            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted "
                            "AND pid IN (SELECT pid FROM pg_stat_activity "
                            "WHERE application_name='sig-tec-ops-rename')").fetchone()[0]
                        if waiting >= 2:
                            break
                        time.sleep(0.05)
                    self.assertGreaterEqual(waiting, 2)
                finally:
                    gate.execute('SELECT pg_advisory_unlock(%s)', (key,))
                results = [job.result() for job in jobs]
        self.assertEqual([code for code, _ in results], [0, 0])
        self.assertEqual(sorted(len(result['resolved']) for _, result in results), [0, 2])
        self.verify_terminal('COMMIT', [])


if __name__ == '__main__':
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryIntegration)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        'executed_at_utc': datetime.now(timezone.utc).isoformat(),
        'base_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_note': 'Cambios de ops/ sin commit; ejecutar el comando para regenerar evidencia.',
        'command': 'ops/.venv/bin/python -B ops/test_recovery.py',
        'python': sys.version.split()[0], 'psycopg': psycopg.__version__,
        'servers': getattr(RecoveryIntegration, 'versions', {}),
        'success': result.wasSuccessful(), 'tests': result.testsRun,
        'duration_seconds': round(time.monotonic() - started, 3),
        'protected_rows_before': {table: len(rows) for table, rows in
                                  getattr(RecoveryIntegration, 'protected', {}).items()},
        'scenarios': RESULTS,
        'fault_methods': {
            'checkpoints': 'os._exit(86) en un proceso hijo; PostgreSQL y Docker no se detienen.',
            'unreachable_central': 'TCP a un puerto reservado sin listener, solo en el worker.',
            'uncertain_abort': 'ABORT real confirmado por PostgreSQL; se oculta su respuesta al recuperador.',
            'missing_branch': 'Lectura simulada de rama ausente; no se destruyen ramas con COMMIT.',
        },
    }
    (ROOT / 'recovery-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
