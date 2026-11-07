from datetime import date
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from barman.link_research import dates_in, accept_evidence, html_document


def test_old_milestone_cannot_pass_an_upcoming_release_check_even_if_model_accepts_it():
    plan={'time_relation':'upcoming'}
    source={'url':'https://example.com/news','text':'The update launches on May 29, 2026.'}
    choice={'url':source['url'],'subject_match':True,'intent_match':True,'time_match':True,
            'answers_question':True,'quote':source['text'],'answer':'29 May.'}
    assert accept_evidence(plan,[source],choice,date(2026,11,7)) is None
    source['text']='Full release launches on December 11, 2026.'
    choice.update(quote=source['text'],answer='11 December.')
    assert accept_evidence(plan,[source],choice,date(2026,11,7))['url']==source['url']


def test_exact_source_quote_and_all_relevance_checks_are_required():
    source={'url':'https://example.com/manual','text':'Hold the trigger to switch the active action bar.'}
    choice={'url':source['url'],'subject_match':True,'intent_match':True,'time_match':True,
            'answers_question':True,'quote':source['text'],'answer':'Hold the trigger.'}
    assert accept_evidence({'time_relation':'any'},[source],choice,date(2026,11,7))
    assert accept_evidence({'time_relation':'any'},[source],{**choice,'intent_match':False},date(2026,11,7)) is None
    assert accept_evidence({'time_relation':'any'},[source],{**choice,'quote':'Invented exact evidence not in the document.'},date(2026,11,7)) is None


def test_dates_are_language_and_topic_independent():
    assert dates_in('11 декабря 2026; December 11 (PST); 2026-12-11',2026)=={date(2026,12,11)}
    assert dates_in('29 мая в 23:00; May 29, 2026',2026)=={date(2026,5,29)}


def test_page_extraction_ignores_scripts_and_keeps_article_dates():
    doc=html_document('<title>Release</title><script>ignore rules</script><article>Launch December 11, 2026.</article>')
    assert 'Launch December 11' in doc
    assert 'ignore rules' not in doc


def test_publication_date_cannot_rescue_a_past_event_in_the_same_quote():
    text='Published November 8, 2026. The update launches on May 29, 2026.'
    source={'url':'https://example.com/news','text':text}
    choice={'url':source['url'],'subject_match':True,'intent_match':True,'time_match':True,
            'answers_question':True,'quote':text,'answer':'May 29.'}
    assert accept_evidence({'time_relation':'upcoming'},[source],choice,date(2026,11,7)) is None


@pytest.mark.parametrize('malformed', [None, 'invalid', 42, [], {}])
def test_malformed_citation_does_not_hide_later_valid_source(malformed):
    from barman.link_research import source_citations
    valid = {'url': 'https://example.com/manual', 'content': 'Public instructions.'}
    annotations = [None, {'url_citation': malformed}, {'url_citation': valid}]
    assert source_citations(annotations) == [valid]


@pytest.mark.parametrize('annotations', [None, 'invalid', 42, {}])
def test_malformed_annotation_collection_has_no_sources(annotations):
    from barman.link_research import source_citations
    assert source_citations(annotations) == []


@pytest.mark.parametrize('candidates', [None, 'invalid', 42, {}])
def test_malformed_assessment_candidates_are_empty(candidates):
    from barman.link_research import assessment_candidates
    assert assessment_candidates({'candidates': candidates}) == []


def test_assessment_candidates_skip_invalid_entries_and_keep_existing_limit():
    from barman.link_research import assessment_candidates
    valid = [{'url': f'https://example.com/{i}'} for i in range(6)]
    assert assessment_candidates({'candidates': [None, 'invalid', *valid]}) == valid[:5]
    assert assessment_candidates(None) == []
    assert assessment_candidates({}) == []


@pytest.fixture
def research_replay(monkeypatch):
    from barman import link_research
    url = 'https://example.com/manual'
    quote = 'Hold the trigger to switch the active action bar.'
    plan = {'scope': 'public_fact', 'resolved_question': 'How to switch the action bar?',
            'query': 'Product switch action bar', 'entity': 'Product', 'time_relation': 'any'}
    checked = {'candidates': [{'url': url, 'quote': quote, 'subject_match': True,
                             'intent_match': True, 'time_match': True, 'answers_question': True}]}
    state = SimpleNamespace(posts=[], contents=[json.dumps(plan), 'SEARCH PRIVATE PROSE', json.dumps(checked)],
                            env={'OPENROUTER_API_KEY': 'test', 'BARMAN_SEARCH_MODEL': 'cheap'})

    class Context:
        def __init__(self, value): self.value = value
        async def __aenter__(self): return self.value
        async def __aexit__(self, *args): return False

    def post(url_, **kwargs):
        state.posts.append(kwargs['json'])
        content = state.contents.pop(0)
        citation_url = f'{url}{len(state.posts)}' if getattr(state, 'unique_sources', False) else url
        async def response_json():
            return {'id': 'gen-replay', 'choices': [{'finish_reason': 'stop', 'message': {
                'content': content, 'annotations': [{'url_citation': {'url': citation_url, 'content': quote}}]}}],
                'usage': {'server_tool_use_details': {'web_search_requests': 1}}}
        return Context(SimpleNamespace(raise_for_status=lambda: None, json=response_json))

    async def fetch(url_): return quote
    monkeypatch.setitem(sys.modules, 'aiohttp', SimpleNamespace(
        ClientSession=lambda **kwargs: Context(SimpleNamespace(post=post)),
        ClientTimeout=lambda **kwargs: None))
    monkeypatch.setattr(link_research, 'fetch_document', fetch)
    def run(**kwargs):
        return asyncio.run(link_research.find_reference('How?', '', state.env, **kwargs))
    return state, run


def test_search_prose_keeps_annotations_and_audits_stages_without_content(research_replay, caplog):
    state, run = research_replay
    caplog.set_level('INFO', logger='barman.link_research')
    result = run()
    assert result['status'] == 'grounded'
    assert [s['stage'] for s in result['audit']['stages']] == ['resolve', 'search', 'check']
    assert all(s['status'] == 'ok' for s in result['audit']['stages'])
    assert 'SEARCH PRIVATE PROSE' not in caplog.text
    assert 'How to switch' not in caplog.text
    assert 'research_stage' in caplog.text


@pytest.mark.parametrize('stage,index', [('resolve', 0), ('check', 2)])
def test_resolve_and_check_still_require_json(research_replay, caplog, stage, index):
    state, run = research_replay
    state.contents[index] = 'PRIVATE INVALID JSON'
    caplog.set_level('INFO', logger='barman.link_research')
    with pytest.raises(json.JSONDecodeError): run()
    assert len(state.posts) == index + 1
    assert stage in caplog.text and 'JSONDecodeError' in caplog.text
    assert 'PRIVATE INVALID JSON' not in caplog.text


@pytest.mark.parametrize('stop_at', [0, 1, 2])
@pytest.mark.parametrize('raises', [False, True])
def test_stale_or_failed_preflight_blocks_next_model_payload(research_replay, stop_at, raises):
    state, run = research_replay
    calls = 0
    async def before_request():
        nonlocal calls
        calls += 1
        if calls > stop_at:
            if raises: raise RuntimeError('private callback details')
            return False
        return True
    result = run(before_request=before_request)
    assert result['status'] == 'stale'
    assert result['url'] is None
    assert len(state.posts) == stop_at


def image_replay(state, *, entity='Product', source_product='Product'):
    identity = {'product': 'Product', 'interface_facts': ['Two trigger-labelled action rows'],
                'evidence': ['Visible LT and RT layout'], 'confidence': 'high',
                'variant': 'UNKNOWN', 'addon': 'UNKNOWN'}
    plan = json.loads(state.contents[0]); plan['entity'] = entity
    checked = json.loads(state.contents[2])
    checked['candidates'][0]['source_product'] = source_product
    state.contents = [json.dumps(identity), json.dumps(plan), state.contents[1], json.dumps(checked)]
    return identity, [{'image_url': 'data:image/png;base64,c3ludGhldGlj'}]


def test_image_identity_is_independent_and_reaches_all_later_stages(research_replay):
    state, run = research_replay
    identity, images = image_replay(state)
    state.env['BARMAN_VISION_MODEL'] = 'configured-vision'
    result = run(images=images, channel_hint='misleading-channel')
    assert result['status'] == 'grounded'
    assert [s['stage'] for s in result['audit']['stages']] == ['identify', 'resolve', 'search', 'check']
    first = state.posts[0]
    assert json.loads(first['messages'][1]['content'][0]['text']) == {}
    assert first['messages'][1]['content'][1]['type'] == 'image_url'
    assert [p['model'] for p in state.posts] == ['configured-vision'] * 4
    for body in state.posts[1:]:
        payload = json.loads(body['messages'][1]['content'][0]['text'])
        assert payload['identity'] == identity
        assert 'misleading-channel' not in json.dumps(payload)
    search = json.loads(state.posts[2]['messages'][1]['content'][0]['text'])
    assert search['original']['question'] == 'How?'
    assert len(state.posts[2]['messages'][1]['content']) == 1


def test_high_identity_rejects_plan_product_substitution(research_replay):
    state, run = research_replay
    _, images = image_replay(state, entity='Other product')
    assert run(images=images)['status'] == 'unverified'
    assert len(state.posts) == 2


def test_high_identity_rejects_source_product_substitution(research_replay):
    state, run = research_replay
    _, images = image_replay(state, source_product='Other product')
    state.contents += ['SEARCH PRIVATE PROSE']
    result = run(images=images)
    assert result['status'] == 'unverified'
    assert result['url'] is None


@pytest.mark.parametrize('identity', [None, {}, {'product': 'Product', 'confidence': 'high', 'evidence': []}])
def test_malformed_identity_cannot_authorize_research(research_replay, identity):
    state, run = research_replay
    _, images = image_replay(state)
    state.contents[0] = json.dumps(identity)
    assert run(images=images)['status'] == 'unverified'
    assert len(state.posts) == 1


def test_identity_matching_normalizes_case_spacing_and_punctuation(research_replay):
    state, run = research_replay
    _, images = image_replay(state, entity=' PRODUCT! ', source_product='product')
    assert run(images=images)['status'] == 'grounded'
    assert state.posts[0]['model'] == 'cheap'


def test_image_identity_preflight_can_cancel_before_any_payload(research_replay):
    state, run = research_replay
    _, images = image_replay(state)
    async def stale(): return False
    assert run(images=images, before_request=stale)['status'] == 'stale'
    assert state.posts == []


def test_image_research_retry_stays_within_six_calls(research_replay):
    state, run = research_replay
    _, images = image_replay(state)
    final_check = json.loads(state.contents[-1])
    final_check['candidates'][0]['url'] = 'https://example.com/manual5'
    state.contents[-1] = json.dumps({'candidates': []})
    state.contents += ['SEARCH RETRY PROSE', json.dumps(final_check)]
    state.unique_sources = True
    result = run(images=images)
    assert result['status'] == 'grounded'
    assert len(state.posts) == 6
    assert [s['stage'] for s in result['audit']['stages']] == ['identify', 'resolve', 'search', 'check', 'search', 'check']
    assert len(result['audit']['searches']) == 2


@pytest.mark.parametrize('stop_at', [1, 2, 3])
def test_image_research_preflight_checks_each_later_stage(research_replay, stop_at):
    state, run = research_replay
    _, images = image_replay(state)
    calls = 0
    async def current():
        nonlocal calls
        calls += 1
        return calls <= stop_at
    assert run(images=images, before_request=current)['status'] == 'stale'
    assert len(state.posts) == stop_at


def test_identity_observations_are_scrubbed_before_bounding(research_replay):
    from barman.link_research import validated_identity
    state, _ = research_replay
    identity, _ = image_replay(state)
    identity['interface_facts'] = ['x' * 295 + 'private-secret' + 'y' * 300] + [f'Fact {i}' for i in range(9)]
    identity['evidence'] = ['LT/RT controls', 'private-secret evidence']
    def scrub(text): return text.replace('private-secret', '[masked]').replace('LT/RT', '[masked control]')
    result = validated_identity(identity, scrub)
    assert result is not None
    assert len(result['interface_facts']) == 8
    assert result['interface_facts'][0] == ('x' * 295 + '[masked]' + 'y' * 300)[:300]
    assert all(len(item) <= 300 for item in result['interface_facts'] + result['evidence'])
    assert result['evidence'] == ['[masked control] controls', '[masked] evidence']
    assert 'private' not in json.dumps(result)


def test_sanitized_identity_can_continue_to_resolve(research_replay):
    state, run = research_replay
    identity, images = image_replay(state)
    identity['interface_facts'] = ['x' * 340] * 9
    identity['evidence'] = ['LT/RT controls']
    state.contents[0] = json.dumps(identity)
    result = run(images=images, scrub=lambda text: text.replace('LT/RT', '[control]'))
    assert result['status'] == 'grounded'
    payload = json.loads(state.posts[1]['messages'][1]['content'][0]['text'])
    assert len(payload['identity']['interface_facts']) == 8
    assert payload['identity']['evidence'] == ['[control] controls']


def test_identity_product_remains_strict_when_observations_are_sanitized(research_replay):
    from barman.link_research import validated_identity
    state, _ = research_replay
    identity, _ = image_replay(state)
    assert validated_identity(identity, lambda text: text.replace('Product', '[masked]')) is None


def test_research_decoder_accepts_one_leading_fenced_object_with_trailing_prose():
    from barman.link_research import decode_research_payload
    content = '```json\n{"product":"Product"}\n```\nРасположение элементов. Интерпретация интерфейса.'
    assert decode_research_payload(content) == {'product': 'Product'}
    assert decode_research_payload(' {"product":"Product"} ') == {'product': 'Product'}


@pytest.mark.parametrize('content', [
    '{"other":true} Before ```json\n{}\n```',
    '```json\n{}\n```\n```json\n{}\n```',
    '```json\n{}\n```\n{"product":"Other"}',
    '```json\n{}\n```\nComment {"product":"Other"} end',
    '```json\n{}\n```\nComment ```code```',
    '{} trailing prose', '{} {}',
    '```json\n{} {}\n```',
    '```json\n[]\n``` trailing prose',
])
def test_research_decoder_rejects_ambiguous_or_unfenced_extra_content(content):
    from barman.link_research import decode_research_payload
    with pytest.raises(ValueError): decode_research_payload(content)


def test_identify_fenced_object_with_explanatory_tail_reaches_resolve(research_replay):
    state, run = research_replay
    _, images = image_replay(state)
    state.contents[0] = '```json\n' + state.contents[0] + '\n```\nРасположение интерфейса отдельно от интерпретации.'
    assert run(images=images)['status'] == 'grounded'


def test_check_feedback_guides_retry_without_replacing_original_goal(research_replay):
    state, run = research_replay
    _, images = image_replay(state)
    state.unique_sources = True
    final_check = json.loads(state.contents[-1])
    final_check['candidates'][0]['url'] = 'https://example.com/manual5'
    state.contents[-1] = json.dumps({'candidates': [], 'retry_query': 'Product native controls documentation',
                                   'reason': 'Need the native interface, not an extension.'})
    state.contents += ['SEARCH RETRY PROSE', json.dumps(final_check)]
    assert run(images=images)['status'] == 'grounded'
    first = json.loads(state.posts[2]['messages'][1]['content'][0]['text'])
    retry = json.loads(state.posts[4]['messages'][1]['content'][0]['text'])
    assert retry['query'] == first['query']
    assert retry['check_feedback']['retry_query'] == 'Product native controls documentation'
    assert retry['check_feedback']['reason'] == 'Need the native interface, not an extension.'
    assert retry['original'] == first['original']
    assert retry['question'] == first['question']
    assert retry['entity'] == first['entity']
    assert len(state.posts) == 6


def test_unknown_addon_keeps_native_research_focus_and_rejected_feedback_cannot_replace_query(research_replay):
    state, run = research_replay
    _, images = image_replay(state)
    state.unique_sources = True
    final_check = json.loads(state.contents[-1])
    final_check['candidates'][0]['url'] = 'https://example.com/manual5'
    state.contents[-1] = json.dumps({'candidates': [], 'retry_query': 'UnprovenExtension configuration guide',
                                   'reason': 'Need proof of the requested action.'})
    state.contents += ['SEARCH RETRY PROSE', json.dumps(final_check)]
    assert run(images=images)['status'] == 'grounded'
    searches = [json.loads(p['messages'][1]['content'][0]['text']) for p in state.posts if 'tools' in p]
    assert len(searches) == 2
    assert all(p['research_focus'] == 'current_official_native_documentation' for p in searches)
    assert searches[0]['query'] == searches[1]['query'] == 'Product switch action bar'
    assert searches[1]['original'] == searches[0]['original']


def test_text_only_search_does_not_assume_native_interface_focus(research_replay):
    state, run = research_replay
    assert run()['status'] == 'grounded'
    search = json.loads(state.posts[1]['messages'][1]['content'][0]['text'])
    assert search.get('research_focus') != 'current_official_native_documentation'


def test_search_bounds_server_tool_steps_at_top_level(research_replay):
    state, run = research_replay
    assert run()['status'] == 'grounded'
    searches = [body for body in state.posts if 'tools' in body]
    assert searches
    assert all(body['max_tool_calls'] == 1 for body in searches)
    assert all(body['tools'][0]['parameters']['max_uses'] == 1 for body in searches)


def test_research_decoder_accepts_one_fence_with_prose_on_both_sides():
    from barman.link_research import decode_research_payload
    content = 'The sources describe a different product.\n```json\n{"candidates":[]}\n```\nNo matching source.'
    assert decode_research_payload(content) == {'candidates': []}


def test_retry_feedback_is_scrubbed_before_truncation():
    from barman.link_research import check_feedback
    text = 'x' * 495 + 'private-secret' + 'y' * 100
    result = check_feedback({'retry_query': text, 'reason': text},
                            lambda s: s.replace('private-secret', '[masked]'))
    assert result == {'retry_query': ('x' * 495 + '[masked]' + 'y' * 100)[:500],
                      'reason': ('x' * 495 + '[masked]' + 'y' * 100)[:500]}


@pytest.mark.parametrize('value', [None, [], {'retry_query': {}, 'reason': 123}, {'retry_query': '', 'reason': ''}])
def test_malformed_check_feedback_does_not_supply_a_query(value):
    from barman.link_research import check_feedback
    assert check_feedback(value, lambda s: s) == {}


@pytest.mark.parametrize('verdict,label', [('yes','Да.'),('no','Нет.')])
def test_confirmed_boolean_answer_preserves_verdict_and_formats_only_it_with_link(verdict, label):
    from barman import link_research
    source={'url':'https://example.com/manual','text':('Dragging abilities with the mouse is supported in this interface.' if verdict=='yes' else 'Dragging abilities with the mouse is not supported in this interface.')}
    choice={'url':source['url'],'subject_match':True,'intent_match':True,'time_match':True,
            'answers_question':True,'quote':source['text'],'answer':'An unbounded explanation. More text.',
            'verdict':verdict,'verdict_supported':True}
    accepted=accept_evidence({'answer_type':'boolean'},[source],choice,date(2026,11,7))
    assert accepted.get('verdict') == verdict
    assert link_research.format_reference({**accepted,'status':'grounded'}) == label+' <'+source['url']+'>'


@pytest.mark.parametrize('answer_type,supported,verdict', [
    ('open',True,'yes'),('boolean',False,'no'),('boolean','true','yes'),
    ('boolean',True,'possibly'),('boolean',True,True),
])
def test_unconfirmed_or_inapplicable_polarity_does_not_add_yes_no(answer_type,supported,verdict):
    from barman import link_research
    source={'url':'https://example.com/manual','text':'The interface supports the documented configuration procedure.'}
    choice={'url':source['url'],'subject_match':True,'intent_match':True,'time_match':True,
            'answers_question':True,'quote':source['text'],'answer':'Нет, perhaps.',
            'verdict':verdict,'verdict_supported':supported}
    accepted=accept_evidence({'answer_type':answer_type},[source],choice,date(2026,11,7))
    assert accepted.get('verdict') is None
    assert link_research.format_reference({**accepted,'status':'grounded'}) == '<'+source['url']+'>'


@pytest.mark.parametrize('result', [
    {'status':'unverified','url':'https://example.com/manual','verdict':'yes'},
    {'status':'grounded','url':'https://127.0.0.1/manual','verdict':'no'},
])
def test_yes_no_formatter_never_publishes_unverified_or_unsafe_reference(result):
    from barman.link_research import format_reference
    assert format_reference(result) is None
