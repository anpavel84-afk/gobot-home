"""A-owned wiring to the existing, read-only HOST-B Monika factory.
No computer microphone, models download, new recognizer, training or logging.
The Owner authorized experimental events explicitly; acoustic acceptance is open.
"""
from __future__ import annotations
from pathlib import Path
import importlib,sys,subprocess


def source_version(b_root:Path)->str:
    return subprocess.check_output(['git','-C',str(b_root),'rev-parse','HEAD'],text=True).strip()


def make_owner_authorized_factory(b_root:Path,models_root:Path,b_site:Path):
    # Reuse B's exact source and preinstalled wheel in this isolated process only.
    # A's canonical WakeEvent class is passed explicitly to avoid duplicate types.
    b_root=Path(b_root).resolve();models_root=Path(models_root).resolve()
    path=b_root/'services'/'voice'
    if not (path/'host_wake_lab'/'monika_bridge.py').is_file():
        raise RuntimeError('HOST_B_MONIKA_FACTORY_MISSING')
    if importlib.util.find_spec('vosk') is None:
        if not (b_site/'vosk'/'__init__.py').is_file():
            raise RuntimeError('EXISTING_ISOLATED_VOSK_WHEEL_MISSING')
        sys.path.append(str(b_site))
    sys.dont_write_bytecode=True
    # Append, never prepend: B also contains an obsolete host_stream.py.
    # Only the namespaced host_wake_lab package comes from B; A owns transport.
    sys.path.append(str(path))
    transport=importlib.import_module('host_stream')
    if Path(transport.__file__).resolve().parent!=Path(__file__).resolve().parent:
        raise RuntimeError('HOST_A_TRANSPORT_IMPORT_MUST_NOT_BE_SHADOWED')
    from host_wake_lab.monika_bridge import make_monika_factory
    from host_wake_contract import WakeEvent
    factory=make_monika_factory(models_root,allow_experimental_events=True,
                                isolated_hardware_test=True,wake_event_type=WakeEvent)
    return lambda: MonikaEndpointAdapter(factory())


class MonikaEndpointAdapter:
    """Delegates PCM->WakeEvent unmodified to B, adds endpoint metadata for A.
    The detector remains VoskOnline from HOST-B; this is not another ASR.
    """
    def __init__(self,inner):
        if inner.candidate_id!='monika' or not inner.activation_approved:
            raise RuntimeError('MONIKA_EXPERIMENTAL_GATE_NOT_ARMED')
        self.inner=inner
        self.suppress_events=False
        self.utterance_endpoint=False
        self.endpoint_sample=-1
        self.frames=0;self.events=0
    def feed_chunk(self,chunk):
        event=self.inner.feed_chunk(chunk)
        hyp=getattr(self.inner.lab,'last_hypothesis',None)
        self.utterance_endpoint=bool(hyp and hyp.endpoint)
        if self.utterance_endpoint:
            self.endpoint_sample=chunk.end_sample_index
        self.frames+=1
        if event is not None and event.phrase_id!='monika':
            raise RuntimeError('ONLY_MONIKA_IS_AUTHORIZED')
        if self.suppress_events:return None
        if event is not None:self.events+=1
        return event
    def reset(self):
        self.inner.reset()
        self.utterance_endpoint=False;self.endpoint_sample=-1
