import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile
import tarfile
import io

spec = importlib.util.spec_from_file_location('unpack', Path(__file__).resolve().parents[1] / 'vscode-extension/src/unpack-model.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class UnpackTest(unittest.TestCase):
    def test_extract_and_reject_traversal_and_links(self):
        for filename, mode in [('model/README.md', 0), ('../outside', 0), ('/outside', 0), ('link', 0o120777 << 16)]:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = root / 'package.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    item = zipfile.ZipInfo(filename)
                    item.external_attr = mode
                    z.writestr(item, 'model documentation')
                if filename == 'model/README.md':
                    m.unpack(root, archive)
                    self.assertEqual((root/'contents/model/README.md').read_text(), 'model documentation')
                    with self.assertRaises(FileExistsError): m.unpack(root, archive)
                else:
                    with self.assertRaises(ValueError): m.unpack(root, archive)
                    self.assertFalse((root/'contents').exists())

    def test_tar_extract_and_reject_links(self):
        for unsafe in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = root / 'package.tar.gz'
                with tarfile.open(archive, 'w:gz') as t:
                    item = tarfile.TarInfo('model/README.md')
                    if unsafe:
                        item.type = tarfile.SYMTYPE
                        item.linkname = '/tmp/outside'
                        t.addfile(item)
                    else:
                        item.size = 5
                        t.addfile(item, io.BytesIO(b'model'))
                if unsafe:
                    with self.assertRaises(ValueError): m.unpack(root, archive)
                else:
                    m.unpack(root, archive)
                    self.assertEqual((root/'contents/model/README.md').read_text(), 'model')


if __name__ == '__main__': unittest.main()
