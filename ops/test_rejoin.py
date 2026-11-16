"""Pruebas puras y de inspección real sin mutar bases ni recursos Docker."""
import json
import unittest
from unittest.mock import patch

import backup
import rejoin
import rename
from verify import inventory


def sequence(**changes):
    return {'seqstart':1,'seqincrement':5,'seqcycle':False,'seqmax':2**63-1,
            'last_value':51,'is_called':True,**changes}


class PlannerTests(unittest.TestCase):
    def test_requires_historical_watermark(self):
        self.assertIsNone(rejoin.next_candidate(1,51,sequence(),None)['candidate'])

    def test_skip_cached_values_and_respect_campus_class(self):
        candidate=rejoin.next_candidate(1,46,sequence(last_value=101),99)
        self.assertEqual(candidate['candidate'],106)
        self.assertFalse(candidate['written'])
        self.assertEqual(rejoin.next_candidate(1,1,sequence(last_value=1,is_called=False),1)['candidate'],6)

    def test_reject_bad_increment_overflow_and_contradictory_watermark(self):
        for meta,high in ((sequence(seqincrement=1),100),(sequence(seqcycle=True),100),
                          (sequence(),2**63-1),(sequence(),10)):
            self.assertIsNone(rejoin.next_candidate(1,51,meta,high)['candidate'])

    def test_missing_commit_marker_is_pending(self):
        request={'operation_id':'uuid-test','campus_id':1,'building_id':1,'new_name':'Nombre sintético'}
        states={'central':{'_ops':{'requests':[request], 'decisions':[{'operation_id':'uuid-test','decision':'COMMIT'}],
                                  'audit':[request]}}, 'cartago':{'_ops':{'applied_operations':[]}}}
        result=rejoin.operation_consistency(states)
        self.assertTrue(result['checked'])
        self.assertEqual(result['pending_or_inconsistent'],1)

    def test_orphan_marker_in_campus_without_requests_is_detected(self):
        result=rejoin.operation_consistency({'central':{'_ops':{'requests':[],'decisions':[],'audit':[]}},
            'san_jose':{'_ops':{'applied_operations':[{'operation_id':'orphan','campus_id':2}]}}})
        self.assertEqual(result['orphan_uuids'],1)

    def test_never_offers_execute_mode_with_incomplete_inventory(self):
        plan=rejoin.dry_run({})
        self.assertFalse(plan['execution_supported'])
        self.assertFalse(plan['ready_for_real_rejoin'])
        self.assertTrue(plan['blockers'])

    def test_catalog_queries_never_fetch_credentials_or_advance_sequences(self):
        class Reader:
            def __init__(self): self.statements=[]
            def query(self,statement):
                self.statements.append(statement)
                if "current_setting('transaction_read_only')" in statement:
                    return [{'read_only':'on','wal_level':'logical','max_prepared':'10','archive_mode':'on','in_recovery':False}]
                if 'count(*) AS n FROM pg_prepared_xacts' in statement: return [{'n':0}]
                return []
        reader=Reader()
        with patch.object(backup,'fingerprint',return_value={'tables':{},'extensions':[]}):
            rejoin.collect(reader,'cartago')
        for query in reader.statements:
            self.assertTrue(query.startswith('SELECT '))
            self.assertFalse(any(token in query.lower() for token in ('subconninfo','rolpassword','nextval(','setval(','pg_drop_')))


class ReadOnlyIntegration(unittest.TestCase):
    def test_real_ops_inspection_preserves_all_data_and_containers(self):
        values=rename.configuration()
        before=backup.origin_state(['central','cartago'],values)
        docker_before=inventory()
        result=rejoin.inspect('ops',None,None,1,None,None)
        self.assertTrue(result['read_only'])
        self.assertTrue(result['plan']['two_phase']['checked'])
        self.assertEqual(result['plan']['two_phase']['pending_or_inconsistent'],0)
        self.assertTrue(all(node['settings']['read_only']=='on' for node in result['nodes'].values()))
        self.assertTrue(all('_ops' not in state for state in result['nodes'].values()))
        self.assertNotIn('new_name',json.dumps(result))
        self.assertEqual(backup.origin_state(['central','cartago'],values),before)
        self.assertEqual(inventory(),docker_before)
        result['tests']={'command':'ops/.venv/bin/python -B ops/test_rejoin.py',
                         'pure_tests':7,'live_read_only_tests':1,'result':'passed',
                         'all_source_data_and_prepared_unchanged':True}
        backup.save(rejoin.ROOT/'rejoin-results.json',result)


if __name__=='__main__':
    runner=unittest.TextTestRunner(verbosity=2)
    pure=runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(PlannerTests))
    if not pure.wasSuccessful(): raise SystemExit(1)
    integration=runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(ReadOnlyIntegration))
    raise SystemExit(0 if integration.wasSuccessful() else 1)
