"""Shared public-evidence gate for all four methods; no physical oracle."""


def resolve(prefix):
    row, now = prefix[-1], len(prefix) - 1
    records = row.get('boundary_evidence', [])
    if not records:
        return {'status': 'ABSENT', 'accepted': [], 'rejected': []}
    earlier = [r for r in prefix[:-1] if r['alarm'] and r['asset'] == row['asset']
               and r['task'] == row['task'] and r['target'] == row['target']]
    last = max((r['source_time'] for r in earlier), default=-1)
    existing = {r['acquisition'] for r in prefix}
    accepted, rejected, seen = [], [], set()
    for item in records:
        reason = None
        identity = (item['source_id'], item['acquisition'])
        if item['asset'] != row['asset'] or item['task'] != row['task']:
            reason = 'binding'
        elif item['quality'] != 'GOOD' or item['reliability'] != 'QUALIFIED':
            reason = 'quality_or_qualification'
        elif item['independent_lineage'] is not True or item['acquisition'] in existing or identity in seen:
            reason = 'lineage'
        elif not (0 <= now - item['known_time'] <= 2 and
                  0 <= row['source_time'] - item['physical_time'] <= 2 and
                  item['physical_time'] <= item['known_time'] <= now and
                  last < item['physical_time'] <= row['source_time'] and
                  item['previous_time'] <= item['physical_time']):
            reason = 'future_stale_or_wrong_interval'
        elif item['kind'] == 'RECOVERY':
            if (item['previous_value'], item['value']) != ('ACTIVE', 'RECOVERED'):
                reason = 'not_explicit_recovery'
        elif item['kind'] == 'WORK_ROUND':
            if (item['previous_value'] == item['value'] or not item.get('closes_previous_round')
                    or not item.get('opens_current_round') or not (
                        last < item.get('previous_round_closed_time', -1)
                        <= item.get('current_round_opened_time', -1) <= item['physical_time'])):
                reason = 'not_closed_and_opened_round'
        elif item['kind'] == 'SOURCE_TRANSITION':
            if (item['previous_value'], item['value']) != ('STOP', 'RUN') or item['previous_time'] <= last:
                reason = 'not_independent_stop_then_run'
        else:
            reason = 'unsupported_kind'
        seen.add(identity)
        if reason:
            rejected.append({'kind': item['kind'], 'reason': reason})
        else:
            accepted.append(item)
    rounds = {(r['previous_value'], r['value']) for r in accepted if r['kind'] == 'WORK_ROUND'}
    if len(rounds) > 1:
        return {'status': 'UNKNOWN_REVIEW', 'accepted': [], 'rejected': rejected + [{'kind': 'WORK_ROUND', 'reason': 'contradictory_rounds'}]}
    # Do not cherry-pick a good record while other submitted evidence is bad.
    if rejected or not accepted:
        return {'status': 'UNKNOWN_REVIEW', 'accepted': [], 'rejected': rejected}
    return {'status': 'NEW_BOUNDARY', 'accepted': accepted, 'rejected': []}
