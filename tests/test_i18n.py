import gettext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import i18n
import layout
import manage


class TranslationTest(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,LC_ALL='en_US.UTF-8')
        environment.start()
        self.addCleanup(environment.stop)

    def test_c_locale_keeps_english_like_native_kde(self):
        with patch.dict(os.environ,LC_ALL='C.UTF-8',LANGUAGE='ru'):
            self.assertEqual(i18n.tr('Music'),'Music')

    def test_english_russian_and_unknown_language_fallback(self):
        for language,expected in [('en_US','Music'),('ru_RU','Музыка'),('fr_FR','Music')]:
            with patch.dict(os.environ,LANGUAGE=language):
                self.assertEqual(i18n.tr('Music'),expected)
        with patch.dict(os.environ,LANGUAGE='fr:ru:en'):
            self.assertEqual(i18n.tr('Music'),'Музыка')

    def test_placeholders_are_replaced_as_values_not_translation_source(self):
        with patch.dict(os.environ,LANGUAGE='ru'):
            self.assertEqual(i18n.tr('LEDs: %1',20),'Диодов: 20')
            self.assertEqual(i18n.tr('Strip %1','%2'),'Лента %2')

    def test_backend_errors_and_defaults_follow_language(self):
        for language,word in [('en','overlap'),('ru','пересекаются')]:
            with patch.dict(os.environ,LANGUAGE=language):
                a=dict(id='a',name='A',start=0,count=2,reverse=False,placement='custom')
                with self.assertRaisesRegex(ValueError,word):
                    layout.validate([a,dict(a,id='b')],3)
        with patch.dict(os.environ,LANGUAGE='en'):
            self.assertEqual(layout.legacy(20)[0]['name'],'Strip 1')

    def test_installed_catalogs_work_and_uninstall_removes_only_owned_translations(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.dict(os.environ,HOME=str(root),XDG_DATA_HOME=str(root/'data'),
                            XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),
                            WLED_CONFIG_DIR=str(root/'config/wled-control-desktop'),
                            WLED_RUNTIME_DIR=str(root/'runtime')):
                manage.install(start=False)
                standard=root/'data/locale/ru/LC_MESSAGES'/f'{i18n.DOMAIN}.mo'
                with standard.open('rb') as stream:
                    self.assertEqual(gettext.GNUTranslations(stream).gettext('Music'),'Музыка')
                unrelated=standard.with_name('other-app.mo')
                unrelated.write_bytes(b'unrelated')
                env=dict(os.environ,LANGUAGE='ru')
                code='import i18n; print(i18n.tr("Music"))'
                result=subprocess.run([sys.executable,'-c',code],cwd=root/'data/wled-control',
                                      env=env,check=True,text=True,capture_output=True)
                self.assertEqual(result.stdout.strip(),'Музыка')
                backup=manage.install(start=False)
                manage.rollback(backup,start=False)
                self.assertEqual(standard.read_bytes(),(root/'data/wled-control/locale/ru/LC_MESSAGES'/standard.name).read_bytes())
                manage.remove(start=False)
                self.assertFalse(standard.exists())
                self.assertEqual(unrelated.read_bytes(),b'unrelated')
