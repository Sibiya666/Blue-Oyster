"""Opt-in live research replay in the test container; no Discord client or posting.

Run from an isolated candidate checkout with --profile-home /opt/data. Only the
four anonymized regression episodes below reach the model, never channel history.
Output is a JSON receipt of actual research and would-be log-only replies.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from barman import link_pilot
from barman import link_research
from barman.link_pilot import PilotState

CASES = (
    ('public_link', 'https://dtf.ru/games/5404363', 'что за хуета', None),
    ('time_followup', 'Третий сезон в WARDOGS стартует 12 ноября 2026 года после технических работ с 13:00 до 15:00 UTC',
     'в 18 получается', 'Опачки'),
    ('personal_project', 'Первая версия роя заработала', 'оркестрация иишек?', None),
    ('personal_statement', 'Сколько уже сидишь так?', 'ну у меня там дубль стоит. На сервере у меня работает с ноутом включенным всё', None),
)
CASE_DATES = {'public_link':'2026-11-10','time_followup':'2026-11-12',
              'personal_project':'2026-11-08','personal_statement':'2026-11-08'}


def read_env(home):
    result = {}
    for line in (home / '.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            result[key.strip()] = value.strip().strip('"')
    # The harness does not need (or retain) Discord tokens or private user lists.
    return {k:v for k,v in result.items() if k in
            ('OPENROUTER_API_KEY','BARMAN_SEARCH_MODEL','BARMAN_VISION_MODEL','BARMAN_REFERENCE_TIMEZONE')}


async def replay(case, profile, diagnostics=False):
    label, root_text, question, owner_followup = case
    now = datetime.now(timezone.utc)
    guild = NS(id=10, members=[])
    channel = NS(id=20, guild=guild, name='general')
    people = {uid:NS(id=uid, bot=False, name=f'Anonymous{uid}') for uid in (7,8)}
    def make(mid, uid, text, parent=None, mentions=()):
        return NS(id=mid, author=people[uid], guild=guild, channel=channel,
                  content=text, attachments=[], embeds=[], webhook_id=None,
                  created_at=now-timedelta(seconds=100-mid),
                  mentions=[people[x] for x in mentions],
                  reference=NS(message_id=parent.id, channel_id=20, guild_id=10,
                               resolved=parent) if parent else None)
    root = make(10, 7, root_text)
    message = make(100, 8, question, root)
    after = [make(101,7,owner_followup)] if owner_followup else []
    messages = {m.id:m for m in (root,message,*after)}
    async def fetch(mid): return messages[mid]
    async def history(**kwargs):
        if 'after' in kwargs:
            for item in reversed(after): yield item
        else:
            yield root
    async def forbidden_post(*args,**kwargs):
        raise AssertionError('Discord publication forbidden by replay harness')
    channel.fetch_message, channel.history = fetch, history
    channel.send = message.reply = forbidden_post
    listeners = {}
    bot = NS(user=NS(id=99), get_channel=lambda _:channel,
             add_listener=lambda fn,event:listeners.setdefault(event,fn))
    env = {**profile, 'BARMAN_LINK_PILOT_OWNER':'7','BARMAN_SCOPE_CHANNEL':'20',
           'BARMAN_LINK_PILOT_START':(now-timedelta(minutes=1)).isoformat(),
           'BARMAN_LINK_PILOT_UNTIL':(now+timedelta(minutes=15)).isoformat(),
           'BARMAN_LINK_PILOT_MODE':'log'}
    observations = []
    evidence_checks = []
    search_plans = []
    original = link_pilot.find_reference
    original_accept = link_research.accept_evidence
    original_body = link_research.model_body
    def observe_body(system,payload,model,images=()):
        if diagnostics and system == link_research.SEARCH:
            search_plans.append({k:payload.get(k) for k in ('question','query','entity','time_relation')})
        return original_body(system,payload,model,images)
    def observe_evidence(plan,sources,choice,today):
        if diagnostics:
            evidence_checks.append({'plan':plan, 'choice':choice,
                'reason_code':link_research.evidence_rejection(plan,sources,choice,today)})
        return original_accept(plan,sources,choice,today)
    async def observe(*args,**kwargs):
        kwargs['as_of']=date.fromisoformat(CASE_DATES[label])
        result = await original(*args,**kwargs)
        observations.append(result)
        return result
    link_pilot.find_reference = observe
    link_research.accept_evidence = observe_evidence
    link_research.model_body = observe_body
    try:
        with tempfile.TemporaryDirectory(prefix='barman-pilot-replay-') as temp:
            home=Path(temp);(home/'SOUL.md').write_text('')
            link_pilot.install_link_pilot(bot,env,home)
            await listeners['on_message'](message)
            entry=PilotState(home/'barman/link-pilot.json').entries.get('100',{})
            result=observations[-1] if observations else {}
            return {'case':label,'as_of':CASE_DATES[label],'status':entry.get('status'),
                    'reason_code':entry.get('reason_code'),
                    'candidate_reply':entry.get('candidate_reply'),
                    'supported_answer':result.get('answer'),
                    'supporting_quote':result.get('quote'),
                    'public_references':entry.get('public_references',0),
                    'owner_reply_reviews':entry.get('owner_reply_reviews',[]),
                    'research':entry.get('research',{}),'discord_posts':0,
                    'fixture_evidence_checks':evidence_checks, 'fixture_search_plans':search_plans}
    finally:
        link_pilot.find_reference = original
        link_research.accept_evidence = original_accept
        link_research.model_body = original_body


async def main(args):
    profile=read_env(args.profile_home)
    if args.runtime_env_stdin:
        supplied=json.load(sys.stdin)
        key=supplied.get('OPENROUTER_API_KEY')
        assert isinstance(key,str) and key, 'Runtime provider credential missing'
        profile['OPENROUTER_API_KEY']=key
    assert profile.get('OPENROUTER_API_KEY'), 'Test profile OpenRouter key missing'
    results=[]
    for case in CASES:
        if args.case and case[0] != args.case: continue
        print('Running '+case[0],file=sys.stderr,flush=True)
        result=await replay(case,profile,args.diagnostics);results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if args.output: args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2))
        if result['status']=='error' or result['reason_code']=='owner_review_failed':
            return 1
    good={r['case']:r for r in results}
    if args.case: return 0 if results and results[0]['status'] in ('logged','unverified_or_stale') else 1
    return 0 if (good['public_link']['status']=='logged'
                 and good['time_followup']['status']=='logged'
                 and all(good[k]['status']=='unverified_or_stale' and
                         good[k]['research'].get('resolution',{}).get('scope')!='public_fact'
                         for k in ('personal_project','personal_statement'))) else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-home',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--runtime-env-stdin',action='store_true',
                        help='Read a temporary provider credential from stdin, never arguments or disk')
    parser.add_argument('--case',choices=[c[0] for c in CASES])
    parser.add_argument('--diagnostics',action='store_true',
                        help='Include model decisions only for these synthetic anonymized fixtures')
    args=parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(asyncio.run(main(args)))
