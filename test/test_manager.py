from pathlib import Path
import os,tempfile,unittest
from backend.manage import read_private,write_private

class ManagerConfigurationTests(unittest.TestCase):
    def test_configuration_is_private_and_rejects_symlinks_or_public_files(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'connection.json';write_private(p,{'url':'http://127.0.0.1:4318'})
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            self.assertEqual(read_private(p)['url'],'http://127.0.0.1:4318')
            link=Path(temp)/'linked';link.symlink_to(p)
            with self.assertRaises(ValueError):read_private(link)
            p.chmod(0o644)
            with self.assertRaises(ValueError):read_private(p)

    def test_http_transport_rejects_external_addresses_and_redirects(self):
        from connection import request
        from unittest.mock import patch,MagicMock
        with tempfile.TemporaryDirectory() as temp:
            token=Path(temp)/'token';token.write_text('x'*40);token.chmod(0o600)
            config={'url':'http://127.0.0.1:4318','token_file':str(token)}
            with patch('connection.http.client.HTTPConnection') as connection:
                for url in ['https://example.com','http://example.com','http://127.0.0.1@evil.example','http://127.0.0.1/path']:
                    with self.assertRaises(ValueError):request({**config,'url':url},'/health')
                connection.assert_not_called()
                response=MagicMock();response.status=302;response.read.return_value=b''
                connection.return_value.getresponse.return_value=response
                with self.assertRaises(ValueError):request(config,'/health')
                connection.assert_called_once_with('127.0.0.1',4318,timeout=3)
                self.assertEqual(connection.return_value.request.call_count,1)
                connection.return_value.close.assert_called_once()
