"""Enrollment document preparation, commit and rollback with explicit paths."""
import json
import os
from pathlib import Path
import sys
import tempfile

from i18n import tr


def persist(selected, prefs, config, runtime, preserve_scene=False):
    """Prepare both documents before the USB owner commits its new Device."""
    import layout
    previous=prefs.get('controller') or {}
    sections=None
    if previous.get('mac')==selected['mac'] and prefs.get('sections'):
        try:
            sections=layout.validate(prefs['sections'],selected['count'])
        except ValueError:
            if previous.get('count')==selected['count']:
                raise
    if sections is None:
        sections=[dict(id='main',name=tr("Lighting"),start=0,count=selected['count'],
                       reverse=False,placement='custom')]
    prefs.update(controller=selected,sections=sections,transport='usb')
    if not preserve_scene:
        prefs['equalizer']=False
    documents={runtime/'state.json':dict(ids=[],volumeUntil=0,base={},suspended=False,
                                        resume=None,controller_mac=selected['mac']),
               config/'settings.json':prefs}
    temporary=[]
    retained=set()
    prepared,previous={},{}
    applied=[]

    def stage(path,data,mode):
        fd,name=tempfile.mkstemp(prefix='.wesp-enroll-',dir=path.parent)
        staged=Path(name)
        temporary.append(staged)
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return staged

    try:
        for path,value in documents.items():
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            prepared[path]=stage(path,json.dumps(value).encode(),0o600)
            previous[path]=stage(path,path.read_bytes(),path.stat().st_mode & 0o777) if path.exists() else None
        try:
            for path in documents:
                prepared[path].replace(path)
                applied.append(path)
        except Exception:
            failed=[]
            for path in reversed(applied):
                try:
                    if previous[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        previous[path].replace(path)
                except OSError:
                    if previous[path] is not None:
                        retained.add(previous[path])
                    failed.append(str(path))
            if failed:
                raise RuntimeError(tr('Could not restore controller settings; backups: %1; files: %2',
                                      ', '.join(map(str,retained)), ', '.join(failed)))
            raise
    finally:
        for path in temporary:
            if path not in retained:
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    print('WESP: could not remove enrollment temporary file: '+str(error),file=sys.stderr)
    return prefs

