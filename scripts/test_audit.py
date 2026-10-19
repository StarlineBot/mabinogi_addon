"""Summarize collection ownership/identity and JUnit runtime without running tests."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def audit(inventory, report):
    rows = json.loads(Path(inventory).read_text(encoding='utf-8'))
    identities = defaultdict(list)
    for row in rows:
        key = (row['source'],row['parameters'],json.dumps(row['fixtures'],sort_keys=True))
        identities[key].append(row['node'])
    root = ET.parse(report).getroot()
    cases = list(root.iter('testcase'))
    measured = {(case.get('classname'),case.get('name')) for case in cases}
    measured_rows = [row for row in rows if
                     (row['node'].split('::')[0].removesuffix('.py').replace('/','.') +
                      ''.join('.'+part for part in row['node'].split('::')[1:-1]),
                      row['node'].split('::')[-1]) in measured]
    modules = defaultdict(float)
    for case in cases:
        modules[case.get('classname','')] += float(case.get('time',0))
    return dict(collected=len(rows),groups=dict(Counter(r['group'] for r in rows)),
                measured_groups=dict(Counter(r['group'] for r in measured_rows)),
                exact_duplicates=[v for v in identities.values() if len(v)>1],
                native=[r['node'] for r in rows if r['native']],
                results=dict(executed=len(cases),failures=len(list(root.iter('failure'))),
                             errors=len(list(root.iter('error'))),skipped=len(list(root.iter('skipped')))),
                suites=[dict(s.attrib) for s in root.iter('testsuite')],
                module_seconds=dict(sorted(modules.items(),key=lambda pair:-pair[1])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('inventory')
    parser.add_argument('junit')
    args = parser.parse_args()
    print(json.dumps(audit(args.inventory,args.junit),ensure_ascii=False,indent=2))
