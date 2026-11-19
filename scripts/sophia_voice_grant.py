"""Finite Sophia board acceptance proposal; default is a read-only preview.

This operator tool never changes existing B/C/phone grants or mounts a profile.
prepare writes a NEW DISABLED epoch with expiry 0. authorize requires the exact
owner-approved proposal SHA and starts its one-time two-hour validity. Only the
explicit cue --execute action can call a speech provider, at most once per epoch.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'services/brain'))

from gobot.board_unified import (
    UNIFIED_ACCEPTANCE_PRESETS, UNIFIED_EXPERT_PROFILES, authorize_proposal, create_service_cue, epoch_root,
    prepare_proposal, proposal_summary,
)
from gobot.expert_stream import load_expert_service_cue


def status(root):
    root = Path(root)
    if not (root/'proposal.json').is_file():
        return {'prepared': False, 'enabled': False, 'paid_requests_made': 0}
    proposal = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
    policies = {name: json.loads((root/path).read_text(encoding='utf-8'))
                for name, path in [('realtime', 'policy.json'), ('expert', 'experts/policy.json'),
                                   ('speech', 'speech-policy.json')]}
    counts = {}
    for name, folder in [('realtime', root), ('expert', root/'experts')]:
        if (folder/'usage.sqlite').is_file():
            with sqlite3.connect((folder/'usage.sqlite').as_uri()+'?mode=ro', uri=True) as db:
                counts[name] = db.execute('SELECT count(*) FROM sessions').fetchone()[0]
                if name == 'realtime' and db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_speech_attempts'").fetchone():
                    counts['speech'] = {kind: {'attempts': count, 'estimated_usd_including_pending': cost,
                                               'pending_usage': pending, 'characters': characters}
                        for kind, count, cost, pending, characters in db.execute('''SELECT kind,count(*),
                            coalesce(sum(cost),0),sum(pending),sum(characters)
                            FROM unified_speech_attempts GROUP BY kind''')}
    return {'prepared': True, 'proposal_sha256': proposal['proposal_sha256'],
            'device_id': proposal['device_id'], 'summary': proposal['summary'],
            'policies': {name: {'enabled': p['enabled'], 'expires_at': p['expires_at']}
                         for name, p in policies.items()},
            'activation_record_present': (root/'activation.json').exists(),
            'attempts': counts, 'provider_invoice_cap_guaranteed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preview', 'prepare', 'authorize', 'status', 'cue'],
                        nargs='?', default='preview')
    parser.add_argument('--run-root', type=Path, default=ROOT/'run')
    parser.add_argument('--epoch')
    parser.add_argument('--device-id')
    parser.add_argument('--expert-profile', choices=UNIFIED_EXPERT_PROFILES,
                        help='Preview/prepare only: the single expert profile bound into the new proposal SHA (default SOL_HIGH).')
    parser.add_argument('--acceptance-preset', choices=UNIFIED_ACCEPTANCE_PRESETS,
                        help='Preview/prepare only: initial or the separate joint_review scope; never edits an existing epoch.')
    parser.add_argument('--gateway-config', type=Path, default=ROOT/'data/hardware/gobot-v1/gateway.json')
    parser.add_argument('--owner-approved-proposal-sha256')
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--execute', action='store_true',
                        help='Only with cue: perform the separately authorized single fixed cache generation.')
    args = parser.parse_args(argv)
    if args.execute and args.command != 'cue':
        parser.error('--execute is only valid for the explicitly authorized cue action')
    if args.expert_profile and args.command not in {'preview', 'prepare'}:
        parser.error('--expert-profile is only valid for preview/prepare; authorization uses the exact prepared proposal')
    if args.acceptance_preset and args.command not in {'preview', 'prepare'}:
        parser.error('--acceptance-preset is only valid for preview/prepare; authorization uses the exact prepared proposal')
    acceptance_preset = args.acceptance_preset or 'initial'
    expert_profile = args.expert_profile or ('ARGON_DEEP' if acceptance_preset == 'joint_review' else 'SOL_HIGH')
    root = epoch_root(args.run_root, args.epoch) if args.epoch else None
    if args.command != 'preview' and root is None:
        parser.error('--epoch is required; existing grants are never reused')
    enrolled = None
    if args.gateway_config.is_file():
        enrolled = json.loads(args.gateway_config.read_text(encoding='utf-8')).get('device_id')
    device = args.device_id or enrolled
    if args.command in {'prepare', 'authorize', 'cue'} and enrolled and device != enrolled:
        raise PermissionError('proposal_must_match_enrolled_board')
    if args.command == 'preview':
        result = {'dry_run': True, 'device_id': device,
                  'summary': proposal_summary(expert_profile, acceptance_preset=acceptance_preset),
                  'files_written': 0, 'paid_requests_made': 0}
    elif args.command == 'prepare':
        if not device:
            parser.error('--device-id or an existing enrolled gateway configuration is required')
        result = prepare_proposal(root, device, expert_profile=expert_profile, acceptance_preset=acceptance_preset)
    elif args.command == 'authorize':
        if not args.owner_approved_proposal_sha256:
            parser.error('the exact --owner-approved-proposal-sha256 is required after owner approval')
        manifest = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
        if enrolled and manifest['device_id'] != enrolled:
            raise PermissionError('proposal_must_match_enrolled_board')
        result = authorize_proposal(root, args.owner_approved_proposal_sha256, cache_root=args.cache_root)
    elif args.command == 'status':
        result = status(root)
    else:
        if args.execute:
            manifest = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
            if enrolled and manifest['device_id'] != enrolled:
                raise PermissionError('proposal_must_match_enrolled_board')
            result = asyncio.run(create_service_cue(root, cache_root=args.cache_root))
        else:
            cache = load_expert_service_cue(args.cache_root)
            result = {'dry_run': True, 'status': cache['status'], 'text': cache['text'],
                      'voice': cache['voice'], 'model': cache['model'],
                      'paid_requests_made': 0, 'requires_explicit_execute': cache['status'] != 'ready'}
    if root is not None:
        result['epoch_root'] = str(root)
        result['staging_after_owner_authorization'] = {
            'mount': {'enabled': True, 'profile': 'sophia_unified_acceptance', 'epoch': args.epoch},
            'gateway': {'hardware_expert_consent': True},
            'requires_existing_idle_backup_restart_checks': True,
            'mounted_by_this_command': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
