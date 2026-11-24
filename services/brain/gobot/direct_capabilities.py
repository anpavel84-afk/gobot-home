"""Current device conversation preferences, without changing any permission grant.

The empty voice transport can refresh this bounded metadata. Execution reads the
current owner settings again; an old provider prompt never authorizes a disabled
operation. Full guidance is sent only to the provider, not status or telemetry.
"""
import asyncio

from .conversation_capabilities import (
    compile_instructions, conversation_settings,
    effective_snapshot, public_snapshot, read_conversation_settings,
    require_capability,
)


HEADER = '\nНачало настроек живого общения.\n'
FOOTER = '\nКонец настроек живого общения.\n'


def instruction_block(snapshot):
    # JSON escapes user-provided newlines, so guidance cannot close this block.
    return HEADER+compile_instructions(snapshot)+FOOTER


def replace_instruction_block(instructions, snapshot):
    before, marker, remaining = instructions.partition(HEADER)
    _, end, after = remaining.partition(FOOTER)
    if not marker or not end:
        raise ValueError('conversation_instructions_shape_unavailable')
    return before+instruction_block(snapshot)+after


def quick_capability(quick):
    """Shared native tool dispatcher -> bounded capability ID, never user text."""
    executor = quick.executor
    if executor in {'timer', 'timer_status'}:
        return 'timer'
    if executor == 'quick_clarify' and quick.intent.startswith('timer_'):
        return 'timer'
    if executor == 'clock':
        return 'clock'
    if executor in {'calculator', 'utility'}:
        return 'utilities'
    if executor == 'memory':
        return 'memory'
    if executor == 'settings' and quick.slots.get('operation', '').startswith('weather_'):
        return 'weather'
    return None


class DirectCapabilities:
    def __init__(self, session):
        self.session = session
        self.snapshot = None
        self.applied_revision = None
        self.applied_settings_revision = None
        self.applied_at = None
        self.checked_at = None
        self.error = None
        self._settings = None

    def settings(self):
        s = self.session
        # The enrolled column has one explicit owner row. Do not silently create
        # a replacement or use an unrelated browser's preferences if it is lost.
        if s.offer.client_id.startswith('spotpear-'):
            return read_conversation_settings(s.manager.brain.configuration.devices,
                                              s.offer.device_id, s.offer.client_id)
        # Other already-authorized native clients have a server-loaded profile.
        # The Sophia admin endpoint cannot edit those clients' settings.
        return conversation_settings(s.profile)

    async def current(self):
        s = self.session
        settings = await self.read_settings()
        expert = await asyncio.to_thread(s.experts.status, include_profiles=False)
        timer = getattr(s, 'timers', None)
        delivery = timer.delivery_status() if timer else {'display': 'unconfirmed', 'signal': 'unconfirmed'}
        available = {'state': 'available'}
        availability = {name: dict(available) for name in
                        ('clock', 'timer', 'weather', 'utilities', 'memory', 'visual')}
        availability['timer'].update({key: delivery[key] for key in ('display', 'signal')})
        availability['expert'] = (dict(available) if expert.get('enabled') else
                                 {'state': 'blocked', 'reason': 'expert_admission_unavailable'})
        result = effective_snapshot(settings, availability=availability)
        self.snapshot = result
        self.error = None
        return result

    async def require(self, capability):
        try:
            settings = await self.read_settings()
        except (ValueError, OSError):
            self.error = 'conversation_settings_unavailable'
            raise PermissionError(self.error) from None
        # This is a restrictive preference, never a substitute for the actual
        # executor's admission. Local clocks/timers need no CLI readiness read.
        if settings['skills'].get(capability) is not True:
            raise PermissionError('capability_disabled_by_owner')
        return {'settings_revision': settings['revision']}

    async def read_settings(self):
        settings = await asyncio.to_thread(self.settings)
        self._settings = settings
        self.error = None
        return settings

    def enabled_now(self, capability):
        try:return self.settings()['skills'].get(capability) is True
        except (ValueError, OSError):return False

    def configured_enabled(self, capability):
        """Synchronous last-known flag for already-running optional workers.

        Fresh authority checks precede side effects. This cheap flag prevents a
        previously-disabled optional worker starting on the audio reader path.
        """
        return not self.error and (self._settings is None or
            self._settings['skills'].get(capability) is True)

    def adopt(self, snapshot, *, at=None):
        import time
        if 'capabilities' in snapshot:
            self.snapshot = snapshot
        self.applied_revision = snapshot['revision']
        self.applied_settings_revision = snapshot['settings_revision']
        self.applied_at = time.time() if at is None else at
        self.checked_at = self.applied_at
        self.error = None

    def public(self):
        return public_snapshot(self.snapshot) if self.snapshot is not None else None

    def status(self):
        s = self.session
        desired = self.snapshot or {}
        pending = s._home_context_pending
        if not s.ready or not self.applied_revision:
            state = 'unavailable'
        elif self.error or s._home_context_reason:
            state = 'unconfirmed'
        elif pending and pending.get('capabilities', {}).get('revision') != self.applied_revision:
            state = 'pending'
        elif desired.get('revision') == self.applied_revision:
            state = 'applied'
        else:
            state = 'waiting_idle'
        return {'state': state, 'settings_revision': desired.get('settings_revision'),
                'applied_settings_revision': self.applied_settings_revision,
                'desired_revision': desired.get('revision'), 'applied_revision': self.applied_revision,
                'applied_at': self.applied_at, 'checked_at': self.checked_at,
                'reason': self.error or s._home_context_reason}
