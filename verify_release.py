#!/usr/bin/env python3
"""Source-only hygiene checks; no desktop, network or serial operations."""
import ast
import gettext
import json
from pathlib import Path
import re
import sys


def main():
    root=Path(__file__).resolve().parent
    errors=[]
    for file in root.rglob('*'):
        if not file.is_file() or '__pycache__' in file.parts or '.git' in file.parts:
            continue
        relative=file.relative_to(root)
        if file.suffix in ('.bin','.elf','.log','.sock') or any('backup' in p or p=='reports' for p in relative.parts):
            errors.append(str(relative)+': local/binary artifact')
        if file.suffix=='.mo':
            if (relative.parts[0]!='locale' or len(relative.parts)!=4
                    or relative.parts[2]!='LC_MESSAGES'
                    or file.name!='plasma_applet_org.wledcontrol.desktop.mo'):
                errors.append(str(relative)+': unexpected binary catalog')
            with file.open('rb') as stream:
                gettext.GNUTranslations(stream)
            continue
        text=file.read_text()
        # Absolute private home directories do not belong in public sources.
        if re.search(r'/home/[A-Za-z0-9_.-]+/',text):
            errors.append(str(relative)+': absolute home path')
        if file.suffix=='.py':
            ast.parse(text,filename=str(relative),feature_version=(3,10))
        if file.suffix=='.json':
            json.loads(text)
    if not (root/'LICENSE').read_text().startswith('MIT License\n\nCopyright (c) 2026 Chapman'):
        errors.append('License/author notice missing')
    if errors:
        print('\n'.join(errors))
        return 1
    print('Source checks OK; desktop and hardware acceptance remain separate')
    return 0


if __name__=='__main__':
    sys.exit(main())
