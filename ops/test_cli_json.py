"""La salida de las CLI es JSON ASCII seguro para consolas regionales."""
from contextlib import redirect_stdout
from io import StringIO
import json
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import recover
import rename


class CliJsonTests(unittest.TestCase):
    text = "José Ñandú 東京 🏢"

    def invoke(self, module, arguments, target, result=None, error=None):
        output = StringIO()
        with patch.object(sys, 'argv', [module.__file__, *map(str, arguments)]), \
                patch.object(module, target, return_value=result, side_effect=error), \
                redirect_stdout(output):
            code = module.main()
        raw = output.getvalue()
        self.assertTrue(raw.isascii(), raw)
        return code, json.loads(raw)

    def test_rename_success_preserves_unicode_after_json_decode(self):
        operation = uuid4()
        code, result = self.invoke(rename, (operation, 1, 7, self.text), 'rename',
                                   {'operation_id': str(operation), 'status': 'completed', 'name': self.text})
        self.assertEqual(code, 0)
        self.assertEqual(result['name'], self.text)

    def test_rename_pending_and_error_preserve_unicode_after_json_decode(self):
        operation = uuid4()
        for error, status, code in ((rename.Pending(self.text), 'pending', 2),
                                    (rename.OperationError(self.text), 'error', 1)):
            with self.subTest(status=status):
                actual, result = self.invoke(rename, (operation, 1, 7, self.text), 'rename', error=error)
                self.assertEqual(actual, code)
                self.assertEqual(result['status'], status)
                self.assertEqual(result['message'], self.text)

    def test_recover_success_pending_and_error_preserve_unicode_after_json_decode(self):
        operation = uuid4()
        for result, error, status, code in (
                ({'operation_id': str(operation), 'status': 'completed', 'name': self.text}, None, 'completed', 0),
                (None, rename.Pending(self.text), 'pending', 2),
                (None, rename.OperationError(self.text), 'error', 1)):
            with self.subTest(status=status):
                actual, decoded = self.invoke(recover, (operation,), 'recover', result, error)
                self.assertEqual(actual, code)
                self.assertEqual(decoded['status'], status)
                self.assertEqual(decoded.get('name', decoded.get('message')), self.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
