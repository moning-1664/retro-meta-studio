import pytest
from app import description_translation as module
from app.description_translation import DescriptionTranslator, TranslationError

class Response:
    def __init__(self, status, data): self.status_code, self.data = status, data
    def json(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *args): pass

@pytest.mark.parametrize('reason,expected', [
    ('dailyLimitExceeded','quota'), ('userRateLimitExceeded','quota'),
    ('BILLING_DISABLED','billing'), ('accessNotConfigured','apiDisabled'),
    ('SERVICE_DISABLED','apiDisabled'), ('API_KEY_INVALID','authentication'),
    ('forbidden','permission'), ('API_KEY_SERVICE_BLOCKED','permission'),
])
def test_google_errors(tmp_path, monkeypatch, reason, expected):
    response = Response(403, {'error': {'errors':[{'reason':reason}], 'details':[{'reason':reason}]}})
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: response)
    with pytest.raises(TranslationError, match='ui.translation.'+expected):
        DescriptionTranslator(tmp_path/'cache.db').translate('A game story', 'ko', 'google', 'fake-key')

@pytest.mark.parametrize('message,expected', [('Daily Limit Exceeded','quota'), ('User Rate Limit Exceeded','quota'), ('billing account disabled','billing')])
def test_google_message_fallback(message, expected):
    assert module.google_error_key(Response(403, {'error':{'message':message}})) == 'ui.translation.'+expected

@pytest.mark.parametrize('mode,data,endpoint', [
    ('deepl-free', {'translations':[{'text':'번역문','detected_source_language':'EN'}]}, 'api-free.deepl.com'),
    ('deepl-pro', {'translations':[{'text':'번역문','detected_source_language':'EN'}]}, 'api.deepl.com'),
    ('google', {'data':{'translations':[{'translatedText':'번역문 &amp; 테스트','detectedSourceLanguage':'en'}]}}, 'translation.googleapis.com'),
])
def test_provider_response_cache_and_original(tmp_path, monkeypatch, mode, data, endpoint):
    calls=[]
    def post(url, **kwargs):
        calls.append(url); return Response(200, data)
    monkeypatch.setattr(module.requests, 'post', post)
    translator=DescriptionTranslator(tmp_path/'cache.db')
    result=translator.translate('A game story', 'ko', mode, 'fake-key')
    assert endpoint in calls[0]
    assert result['translated'].startswith('번역문')
    assert '&amp;' not in result['translated']
    translator.remember('game-key',result)
    assert translator.original('game-key',result['translated']) == 'A game story'
    assert translator.original('game-key','external edit') is None
    assert translator.translate('A game story','ko',mode,'fake-key')['cached']
    assert len(calls)==1

@pytest.mark.parametrize('status,expected', [(401,'authentication'),(429,'quota'),(456,'quota'),(500,'serviceError')])
def test_deepl_errors(tmp_path, monkeypatch, status, expected):
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs:Response(status,{}))
    with pytest.raises(TranslationError, match='ui.translation.'+expected):
        DescriptionTranslator(tmp_path/'cache.db').translate('story','ko','deepl-free','fake-key')

def test_malformed_google_error():
    assert module.google_error_key(Response(403, {'error':None})) == 'ui.translation.permission'
