"""Persistent first-seen opponent coverage; never infers unseen card deployments."""
import json
import os
from pathlib import Path


class CardAudit:
    def __init__(self, path, catalogue, unit_types, card_map, resolve_form, expected=''):
        self.path = Path(path)
        self.catalogue, self.unit_types = catalogue, unit_types
        self.card_map, self.resolve_form = card_map, resolve_form
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            self.data = {'schema':1,'expected':[],'observations':{}}
        self.data['catalogue'] = [c[0] for c in catalogue]
        self.names = {c[0].lower():c[0] for c in catalogue}
        for name in expected.split(','):
            name = name.strip()
            if name:
                name = self.names.get(name.lower(),name)
                if name not in self.data['expected']:
                    self.data['expected'].append(name)
        self.save()

    def note(self, key, record):
        if key in self.data['observations']:
            return False
        self.data['observations'][key] = record
        return True

    def observe(self, frame, side, state):
        accepted = {e[0] for e in state['entities']}
        changed = False
        for u in frame.get('u',[]):
            if len(u) < 10 or u[3] == side:
                continue
            name = u[10] if len(u)>10 else ''
            if name in {'KingTower','PrincessTower','Cannoneer','DaggerDuchess','ChefTower'}:
                continue
            entry = self.card_map.get(str(u[6]))
            card = entry['rs_id'] if entry else self.resolve_form(name,self.catalogue)
            label = self.catalogue[card][0] if 0 <= card < len(self.catalogue) else None
            effect = u[9] <= 0 or 'Projectile' in name or 'Container' in name
            stage = 'bridge' if u[0] in accepted else ('effect' if effect else 'dropped')
            key = f'{u[6]}|{name}|{stage}'
            changed |= self.note(key, {'stage':stage,'card':label,'native_card':u[6],
                                      'unit':name,'tick':frame.get('t'),
                                      'reason':('' if stage!='dropped' else
                                                'unknown unit name' if name not in self.unit_types else
                                                'unknown card mapping' if label is None else 'bridge skipped'),
                                      'hp':u[8],'max_hp':u[9]})
        if changed:
            self.save()

    def model(self, row, live, tick):
        changed = False
        for token, feats in zip(row['unit_ids'],row['unit_feats']):
            token = int(token)
            if token < 2 or float(feats[0]) >= .5:
                continue
            idx = token-2
            name = self.catalogue[idx][0] if live else self.unit_types[idx]
            changed |= self.note(f'model|{live}|{name}',
                                 {'stage':'model','card':name if live else None,
                                  'unit':None if live else name,'tick':tick})
        if changed:
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(self.data,f,indent=2,ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,self.path)
        records = list(self.data['observations'].values())
        seen = {r['card'] for r in records if r.get('card') and r['stage'] != 'model'}
        bridged = {r['card'] for r in records if r.get('card') and r['stage']=='bridge'}
        model = {r['card'] for r in records if r.get('card') and r['stage']=='model'}
        not_seen = sorted(set(self.data['expected'])-seen)
        summary = [f'Unique mapped opponent cards observed: {len(seen)}',
                   f'Cards reaching bridge: {len(bridged)}',
                   f'Cards reaching model (card-token mode only): {len(model)}',
                   f'Declared test cards not observed: {len(not_seen)}',
                   ', '.join(not_seen) or '(none)',
                   '\nObserved cards: '+', '.join(sorted(seen)),
                   '\nDropped character forms:']
        summary += [f"{r.get('card') or 'UNKNOWN'} / {r['unit']} / native {r['native_card']}: {r['reason']}"
                    for r in records if r['stage']=='dropped']
        summary += ['\nUnseen is not proof of failed detection: deploy each declared card.',
                    'Spells/effects need not be unit tokens. Coverage uses the local simulator catalogue.',
                    'A model entry proves some instance reached the token input, not correct defence.']
        untested = sorted(set(self.data['catalogue'])-seen)
        summary += [f'\nLocal catalogue cards not yet observed: {len(untested)}',
                    ', '.join(untested),
                    '\nModel unit types observed: '+', '.join(sorted({r['unit'] for r in records
                        if r['stage']=='model' and r.get('unit')}))]
        report = self.path.with_suffix('.txt')
        tmp_report = report.with_suffix('.txt.tmp')
        tmp_report.write_text('\n'.join(summary)+'\n',encoding='utf-8')
        os.replace(tmp_report,report)
