#!/usr/bin/env python3
"""Validate gettext coverage, placeholders and checked-in compiled catalogs."""
import ast
from collections import Counter
import gettext
from pathlib import Path
import re
import subprocess
import tempfile

from i18n import DOMAIN

ROOT=Path(__file__).resolve().parent


def main():
    messages=set()
    for path in ROOT.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr':
                if not node.args or not isinstance(node.args[0],ast.Constant) or not isinstance(node.args[0].value,str):
                    raise ValueError('Translation keys must be literal messages: '+path.name)
                messages.add(node.args[0].value)
    qml=(ROOT/'plasma/org.wledcontrol.desktop/contents/ui/main.qml').read_text()
    import json
    messages.update(json.loads(match[1]) for match in re.finditer(
        r'i18nd\("'+re.escape(DOMAIN)+r'",\s*("(?:\\.|[^"\\])*")',qml))
    if re.search('[А-Яа-яЁё]',qml):
        raise ValueError('Untranslated Russian text in QML source')
    with tempfile.TemporaryDirectory(prefix='wled-catalog-') as directory:
        for source in sorted((ROOT/'locale').glob('*.po')):
            target=Path(directory)/(source.stem+'.mo')
            subprocess.run(['msgfmt','--check','--check-format','-o',str(target),str(source)],check=True,timeout=15)
            compiled=ROOT/'locale'/source.stem/'LC_MESSAGES'/(DOMAIN+'.mo')
            if target.read_bytes()!=compiled.read_bytes():
                raise ValueError('Recompile the catalog: '+str(compiled.relative_to(ROOT)))
            with compiled.open('rb') as stream:
                catalog=gettext.GNUTranslations(stream)
            for message in sorted(messages):
                translated=catalog.gettext(message)
                if translated==message:
                    raise ValueError(source.stem+': missing translation: '+message)
                if Counter(re.findall(r'%[1-9][0-9]*',message))!=Counter(re.findall(r'%[1-9][0-9]*',translated)):
                    raise ValueError(source.stem+': placeholder mismatch: '+message)
    print('PASS: gettext source coverage, placeholders and compiled catalogs ('+str(len(messages))+' messages)')


if __name__=='__main__':
    main()
