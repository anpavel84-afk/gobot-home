"""Permanent testing is not exhausted by eight completed in-memory cards."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from gobot.expert_jobs import ExpertJobs


def harness(monkeypatch, *, permanent=True):
    monkeypatch.setattr('gobot.expert_jobs.resolve_profile', lambda profile: {
        'profile': profile, 'metadata_verified': True, 'requested_label': 'Argon Deep',
        'provider': 'synthetic', 'model': 'synthetic-expert', 'effort': 'medium'})
    session = SimpleNamespace(
        access=SimpleNamespace(effective_scope='guest:synthetic-board', confirmed_profile_id=None),
        offer=SimpleNamespace(conversation_id='synthetic-conversation', device_id='synthetic-board',
                              client_id='synthetic-board', profile_epoch='synthetic-epoch',
                              confirmed_profile_epoch=None, remember=False),
        turns=[], task_revision=lambda: 1)
    policy = SimpleNamespace(allowed_profiles=['ARGON_DEEP'], owner_terminal=permanent)
    jobs = ExpertJobs(session, budget=SimpleNamespace(policy=lambda: policy))
    turn = SimpleNamespace(id='synthetic-turn', query='Попроси эксперта сравнить варианты.', answer='')
    return jobs, turn


def completed(jobs, turn):
    public = jobs.propose(turn.query, 'ARGON_DEEP', turn)
    job = jobs.jobs[public['job_id']]
    job.state = 'completed'
    job.returned = True
    return job


def test_many_completed_jobs_keep_recent_cards_and_replay_protection(monkeypatch):
    jobs, turn = harness(monkeypatch)
    first = completed(jobs, turn)
    jobs.used_confirmation_turns.add('already-spent-confirmation')
    jobs.context_versions[first.id] = ('completed',)
    last = None
    for _ in range(20):
        last = completed(jobs, turn)
    assert len(jobs.jobs) == 8
    assert first.id not in jobs.jobs and first.id not in jobs.context_versions
    assert jobs.pending is last and last.id in jobs.jobs
    assert jobs.used_confirmation_turns == {'already-spent-confirmation'}


def test_inflight_playback_and_worker_are_not_evicted(monkeypatch):
    jobs, turn = harness(monkeypatch)
    playing = completed(jobs, turn)
    playing.external_narration = True
    worker = completed(jobs, turn)
    worker.worker = SimpleNamespace(done=lambda: False)
    running = completed(jobs, turn)
    running.state = 'running'
    for _ in range(12):
        completed(jobs, turn)
    assert {playing.id, worker.id, running.id} <= set(jobs.jobs)
    assert len(jobs.jobs) == 8


def test_finite_grants_keep_existing_capacity_behavior(monkeypatch):
    jobs, turn = harness(monkeypatch, permanent=False)
    for _ in range(8):
        completed(jobs, turn)
    with pytest.raises(ValueError, match='expert_job_capacity'):
        jobs.propose(turn.query, 'ARGON_DEEP', turn)


def test_unconfirmed_replaced_proposals_do_not_exhaust_terminal(monkeypatch):
    jobs, turn = harness(monkeypatch)
    for _ in range(20):
        jobs.propose('Сравни варианты.', 'ARGON_DEEP', turn)
    assert len(jobs.jobs) == 8
    assert sum(job.state == 'awaiting_confirmation' for job in jobs.jobs.values()) == 1


@pytest.mark.parametrize('outcome', ['success', 'failed', 'cancelled'])
def test_playback_context_delivery_retains_card_across_concurrent_proposal(monkeypatch, outcome):
    async def run():
        jobs, turn = harness(monkeypatch)
        first = completed(jobs, turn)
        first.result = {'display_text': 'Synthetic completed expert answer.'}
        first.external_narration = first.narration_complete = True
        for _ in range(7):
            completed(jobs, turn)
        jobs.session.closed = False
        jobs.session.emit = lambda *args, **kwargs: None
        monkeypatch.setattr(jobs, 'authorized_owner', lambda job: True)
        entered, release = asyncio.Event(), asyncio.Event()
        async def deliver(job, item):
            assert job is first
            entered.set()
            await release.wait()
            if outcome == 'failed':
                raise ConnectionError('synthetic transport loss')
        jobs.session.expert_context_synced = deliver
        delivery = asyncio.create_task(jobs.playback_finished(first.id, first.response_id))
        await entered.wait()
        assert first.playback_complete  # This used to make the still-delivering job evictable.
        completed(jobs, turn)
        assert jobs.jobs[first.id] is first and len(jobs.jobs) == 8
        if outcome == 'cancelled':
            delivery.cancel()
            with pytest.raises(asyncio.CancelledError):
                await delivery
        else:
            release.set()
            assert await delivery is True
        assert not jobs._context_inflight
        if outcome == 'success':
            assert 'expert_context_synced' in first.timings
        completed(jobs, turn)
        assert first.id not in jobs.jobs and first.id not in jobs.context_versions
        assert len(jobs.jobs) == 8
    asyncio.run(run())


def test_context_memory_write_retains_job_until_thread_finishes(monkeypatch):
    async def run():
        jobs, turn = harness(monkeypatch)
        first = completed(jobs, turn)
        first.result = {'display_text': 'Synthetic result.'}
        for _ in range(7):
            completed(jobs, turn)
        jobs.session.closed = False
        monkeypatch.setattr(jobs, 'authorized_owner', lambda job: True)
        entered, release = threading.Event(), threading.Event()
        records = []
        def start(request):
            entered.set()
            assert release.wait(2)
        memory = SimpleNamespace(start=start, finish=lambda *args: records.append(args),
                                 transient={}, transient_lock=threading.Lock())
        jobs.session.manager = SimpleNamespace(brain=SimpleNamespace(memory=memory))
        writing = asyncio.create_task(jobs.record_context(first))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            completed(jobs, turn)
            assert jobs.jobs[first.id] is first
        finally:
            release.set()
        await writing
        assert first.context_recorded and len(records) == 1
        assert not jobs._context_inflight
        completed(jobs, turn)
        assert first.id not in jobs.jobs
    asyncio.run(run())


@pytest.mark.parametrize('change,removed', [
    ({}, True), ({'owner': 'guest:other-board'}, False),
    ({'conversation': 'other-conversation'}, False), ({'epoch': 'other-epoch'}, False),
    ({'status': 'running'}, False),
])
def test_eviction_clears_only_exact_completed_guest_transient(monkeypatch, change, removed):
    jobs, turn = harness(monkeypatch)
    first = completed(jobs, turn)
    for _ in range(7):
        completed(jobs, turn)
    key = 'expert-'+first.id
    row = {'owner': first.owner, 'conversation': first.conversation,
           'epoch': jobs.session.offer.profile_epoch, 'status': 'completed', **change}
    other = {'owner': 'guest:unrelated-board', 'result': 'Keep unrelated RAM context.'}
    memory = SimpleNamespace(transient={key: row, 'unrelated': other}, transient_lock=threading.Lock())
    jobs.session.manager = SimpleNamespace(brain=SimpleNamespace(memory=memory))
    jobs.used_confirmation_turns.add('already-spent')
    completed(jobs, turn)
    assert first.id not in jobs.jobs
    assert (key not in memory.transient) is removed
    assert memory.transient['unrelated'] is other
    assert jobs.used_confirmation_turns == {'already-spent'}


def test_eviction_does_not_touch_profile_context_or_persistent_store(monkeypatch):
    jobs, turn = harness(monkeypatch)
    first = completed(jobs, turn)
    first.profile_id, first.remember = 'synthetic-adult-profile', True
    for _ in range(7):
        completed(jobs, turn)
    key = 'expert-'+first.id
    row = {'owner': first.owner, 'conversation': first.conversation,
           'epoch': jobs.session.offer.profile_epoch, 'status': 'completed'}
    memory = SimpleNamespace(transient={key: row}, transient_lock=threading.Lock())
    class UntouchedStore:
        def __getattr__(self, name):
            raise AssertionError('Pruning must not operate on a persistent result store.')
    jobs.session.manager = SimpleNamespace(brain=SimpleNamespace(memory=memory), expert_store=UntouchedStore())
    completed(jobs, turn)
    assert first.id not in jobs.jobs and memory.transient[key] is row
