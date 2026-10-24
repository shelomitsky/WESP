import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import receiver_assets


class ReceiverAssetsTest(unittest.TestCase):
    def bundle(self,root):
        images=[]
        for name,offset in receiver_assets.OFFSETS.items():
            blob=(name.encode()*10)
            (root/name).write_bytes(blob)
            images.append(dict(file=name,offset=offset,size=len(blob),sha256=hashlib.sha256(blob).hexdigest()))
        data=dict(firmware='WESP',chip='esp32',flash_size=4194304,images=images)
        (root/'manifest.json').write_text(json.dumps(data))
        return data

    def test_exact_offsets_and_checksums_before_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.bundle(root)
            image=receiver_assets.merged(root).read_bytes()
            self.assertEqual(len(image),4194304)
            self.assertEqual(image[:0x1000],b'\xff'*0x1000)
            blob=(root/'firmware.bin').read_bytes()
            self.assertEqual(image[0x10000:0x10000+len(blob)],blob)
            (root/'firmware.bin').write_bytes(blob+b'corrupt')
            with self.assertRaises(ValueError): receiver_assets.merged(root)

    def test_missing_duplicate_or_wrong_offset_cannot_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); data=self.bundle(root)
            data['images'][0]['offset']=0
            (root/'manifest.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError): receiver_assets.validated(root)


if __name__=='__main__': unittest.main()
