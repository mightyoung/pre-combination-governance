"""Notification revision; event association and physical oracle unchanged.

An uncertain card is retained. Only a plausible continuing-context update
defers duplicate physical alert; uncertainty without that context still alerts.
These are synthetic diagnostic rules, not production safety control.
"""
import methods


def continuing_context_candidate(row, earlier, receipt_now):
    if row['quality'] != 'GOOD':
        return False
    matches = [r for r in earlier if r['alarm'] and r['relationship'] == 'VALID'
               and r['quality'] == 'GOOD' and r['target'] == row['target']
               and r['value'] == row['value']
               and r['asset'] == row['asset'] and r['task'] == row['task']
               and 0 <= receipt_now - r['confirmed_time'] <= 2
               and r['source_time'] <= row['source_time']]
    if not matches:
        return False
    last = max(r['source_time'] for r in matches)
    # An observed recovery is evidence for another episode, not an update.
    return not any(r['recovery'] and r['quality'] == 'GOOD' and r['asset'] == row['asset']
                   and last <= r['source_time'] <= row['source_time']
                   for r in earlier + [row])


def escalation(old, new):
    if new == 'CONFLICT_REVIEW':
        return old != new
    if new == 'EXPOSURE_HIGH':
        return old != new
    return new == 'EXPOSURE' and old in (None, 'UNKNOWN')


def step(prefix, method, old):
    result = methods.assess(prefix, method)
    new_cards = set(result['cards'].values()) - set(old.get('cards', {}).values())
    first_event = False
    updates = []
    for alarm_id, card in result['cards'].items():
        if card not in new_cards:
            continue
        index, row = next((i, r) for i, r in enumerate(prefix) if r['id'] == alarm_id)
        deferred = alarm_id in result['possible'] and continuing_context_candidate(row, prefix[:index], len(prefix) - 1)
        if deferred:
            updates.append({'id': alarm_id, 'kind': 'possible_existing_event_update',
                            'association_established': False, 'review_required': True})
        else:
            first_event = True
    reasons = []
    if result['notify'] and first_event:
        reasons.append('new_event_first_alert')
    if result['notify'] and escalation(old.get('risk'), result['risk']):
        reasons.append('risk_escalation')
    if result['priority'] == 'FOLLOW_UP' and old.get('priority') != 'FOLLOW_UP':
        reasons.append('handling_follow_up_only')
    result['notification_reasons'] = reasons
    result['card_updates'] = updates
    # Preserve downgrades/resolutions as state updates, without a
    # physical escalation alert solely because a state changed.
    result['risk_state_update'] = None if old.get('risk') == result['risk'] else {
        'from': old.get('risk'), 'to': result['risk']}
    result["review_notification_reasons"] = ["uncertain_new_alarm_requires_review"] if result["card_updates"] else []
    return result


def run(public):
    if len(public['traces']) != 5 or any(len(t['rows']) != 5 for t in public['traces']):
        raise ValueError('fixed 5x5 boundary scope')
    output, count = [], 0
    for trace in public['traces']:
        previous = {}
        for n in range(1, 6):
            for method in ('M0', 'M1', 'M2', 'M3'):
                count += 1
                if count > 100:
                    raise RuntimeError('method budget')
                result = step(trace['rows'][:n], method, previous.get(method, {}))
                previous[method] = result
                output.append({'trace': trace['id'], 'prefix': n, 'method': method, 'result': result})
    return {'status': 'DEVELOPMENT_ONLY_BOUNDARY_DIAGNOSTIC', 'method_invocations': count, 'rows': output}


if __name__ == '__main__':
    raise SystemExit('Use the bound manual launcher; no naked CLI')
