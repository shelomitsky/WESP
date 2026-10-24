"""Watch the default OUTPUT; microphone selection never affects light capture."""
import logging
import os
import selectors
import subprocess
import threading

LOG=logging.getLogger('wesp-audio')


def capture_command(source,latency_ms,client):
    if source!='@DEFAULT_MONITOR@' and not source.endswith('.monitor'):
        raise ValueError('Only an output monitor may feed lighting')
    return ['parec','--device='+source,'--raw','--format=float32le','--rate=48000',
        '--channels=1','--latency-msec='+str(latency_ms),'--client-name='+client,
        '--stream-name=Desktop output monitor','--property=media.role=music',
        '--property=application.icon_name=wled-control','--property=node.virtual=true',
        '--property=stream.monitor=true']


class OutputMonitor:
    def __init__(self):
        self.source='@DEFAULT_MONITOR@'
        self.stop=threading.Event()
        self.refresh()
        self.thread=threading.Thread(target=self.watch,name='wesp-output-watch',daemon=True)
        self.thread.start()

    def refresh(self):
        try:
            result=subprocess.run(['pactl','get-default-sink'],capture_output=True,
                                  text=True,check=True,timeout=1)
            sink=result.stdout.strip()
            if not sink or len(sink)>512 or '\n' in sink or '\r' in sink or sink.startswith('@'):
                raise ValueError('Invalid default output')
            self.source=sink+'.monitor'
        except (OSError,ValueError,subprocess.SubprocessError):
            # An unavailable tracker must not destroy a healthy recording.
            LOG.debug('Cannot refresh the default output',exc_info=True)

    def watch(self):
        while not self.stop.is_set():
            process=None
            try:
                process=subprocess.Popen(['pactl','subscribe'],stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,env=dict(os.environ,LC_ALL='C'))
                self.refresh()  # Cover a switch during subscription startup.
                pending=bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout,selectors.EVENT_READ)
                    while not self.stop.is_set():
                        if not selector.select(.2):continue
                        data=os.read(process.stdout.fileno(),4096)
                        if not data:break
                        pending.extend(data)
                        while b'\n' in pending:
                            line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                            if b'on server' in line:self.refresh()
                        if len(pending)>8192:pending.clear()
            except (OSError,ValueError):
                LOG.debug('Default output subscription unavailable',exc_info=True)
            finally:
                if process is not None:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    process.stdout.close()
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)
