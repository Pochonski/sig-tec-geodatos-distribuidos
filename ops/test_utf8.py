"""Pruebas sin Docker, ejecutables con unittest en Windows y Linux."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import migrate
import runtime


class UTF8Tests(unittest.TestCase):
    def test_sql_uses_utf8_bytes_independently_of_locale(self):
        statement="SELECT 'José, Ñandú, € y 🏢, 東京';\n"
        answer='José, Ñandú, € y 🏢, 東京'
        with patch.object(migrate.subprocess,'run',return_value=subprocess.CompletedProcess([],0,answer.encode('utf-8'),b'')) as call:
            self.assertEqual(migrate.sql('container-test',statement),answer)
        self.assertEqual(call.call_args.kwargs['input'],statement.encode('utf-8'))
        self.assertNotIn('text',call.call_args.kwargs)
        self.assertIn('PGCLIENTENCODING=UTF8',call.call_args.args[0])

    def test_password_pipe_does_not_recode_sql(self):
        statement="SELECT 'áéíóú ñ 中文';"
        with patch.object(migrate.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'ok',b'')) as call:
            migrate.sql('test',statement,'only-test-value')
        self.assertEqual(call.call_args.kwargs['input'],('only-test-value\n'+statement).encode('utf-8'))

    def test_utf8_bom_and_crlf_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            env=Path(directory)/'prueba.env'
            env.write_bytes('\ufeffNOMBRE="José Ñandú 🏢"\r\nOTRO=東京\r\n'.encode('utf-8'))
            with patch.object(runtime,'config',return_value={'env_file':str(env)}):
                self.assertEqual(runtime.values(),{'NOMBRE':'José Ñandú 🏢','OTRO':'東京'})

    def test_diagnostics_do_not_disclose_sql_or_credentials(self):
        with patch.object(migrate.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'',b'not-for-output')):
            with self.assertRaisesRegex(RuntimeError,'salida omitida'):
                migrate.sql('test',"SELECT 'dato ficticio';",'only-test-value')

    def test_invalid_utf8_is_not_silently_replaced(self):
        with patch.object(migrate.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'\xff',b'')):
            with self.assertRaises(UnicodeDecodeError): migrate.sql('test','SELECT 1')

    def test_integrated_migration_never_inserts_minimal_fixture(self):
        config={'integrated':True,'nodes':{'central':{'cli_password_env':'A'},'san_jose':{'cli_password_env':'B'}}}
        statements=[]
        with patch.object(runtime,'config',return_value=config), patch.object(migrate,'sql',side_effect=lambda c,s:statements.append(s)):
            migrate.apply({'central':'test-central','san_jose':'test-campus'},{'A':'a'*40,'B':'b'*40})
        self.assertEqual(len(statements),2)
        self.assertIn('campus_id = 2',statements[1])
        self.assertIn('ON san_jose.edificios',statements[1])
        self.assertNotIn('CREATE TABLE IF NOT EXISTS cartago.edificios',statements[1])
        self.assertNotIn('Edificio ficticio',statements[1])


if __name__=='__main__': unittest.main(verbosity=2)
