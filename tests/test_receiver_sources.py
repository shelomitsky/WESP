import hashlib,json,tarfile,tempfile,unittest
from pathlib import Path
import build_release,receiver_assets

class ReceiverSourcesTest(unittest.TestCase):
    def fixture(self,root):
        framework=root/'framework';framework.mkdir()
        (framework/'package.json').write_text(json.dumps({'version':'3.20014.231204'}))
        for name in ('cores/esp32/core.cpp','libraries/WiFi/wifi.cpp','variants/esp32/pins_arduino.h'):
            p=framework/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('// test library source\n')
        assets=root/'assets';assets.mkdir();images=[]
        for name,offset in receiver_assets.OFFSETS.items():
            data=name.encode()*10;(assets/name).write_bytes(data)
            images.append(dict(file=name,offset=offset,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
        (assets/'manifest.json').write_text(json.dumps(dict(firmware='WESP',chip='esp32',flash_size=4194304,images=images)))
        return framework,assets

    def test_native_archive_requires_and_contains_rebuild_materials(self):
        import receiver_sources
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);framework,assets=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'source|license|rebuild'):build_release.build(root/'missing',receiver=assets)
            receiver_sources.bundle(framework,assets)
            first=(assets/'arduino-core-sources.tar.gz').read_bytes();receiver_sources.bundle(framework,assets)
            self.assertEqual(first,(assets/'arduino-core-sources.tar.gz').read_bytes())
            with tarfile.open(assets/'arduino-core-sources.tar.gz') as archive:
                self.assertEqual(archive.extractfile('arduino-esp32-2.0.14/cores/esp32/core.cpp').read(),b'// test library source\n')
            path=build_release.build(root/'complete',receiver=assets)
            with tarfile.open(path) as archive:
                manifest=json.load(archive.extractfile('wesp/SOURCE_SHA256.json'))
                for name in receiver_sources.FILES:
                    key='receiver-firmware/'+name
                    self.assertEqual(hashlib.sha256(archive.extractfile('wesp/'+key).read()).hexdigest(),manifest[key])

    def test_wrong_framework_version_cannot_claim_pinned_sources(self):
        import receiver_sources
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);framework,assets=self.fixture(root)
            (framework/'package.json').write_text(json.dumps({'version':'other'}))
            with self.assertRaises(ValueError):receiver_sources.bundle(framework,assets)

if __name__=='__main__':unittest.main()
