from types import SimpleNamespace
import pytest
from bridge.translation import TranslationBridge
from bridge import translation as module

class Registry:
    def __init__(self): self.settings = {'mode':'google','key':'reference'}
    def get_setting(self, *args): return dict(self.settings)
    def set_setting(self, key, value): self.settings = dict(value)

class Jobs:
    def run(self, fn): self.fn = fn; return 'test-job'

@pytest.fixture
def bridge(monkeypatch):
    value = TranslationBridge()
    value.registry = Registry(); value.jobs = Jobs()
    monkeypatch.setattr(module.secrets, 'load', lambda key: 'fake-key')
    return value

def test_requires_success_and_preserves_verification_when_unchanged(bridge, monkeypatch):
    monkeypatch.setattr(module.DescriptionTranslator, 'translate', lambda *args: {'translated':'안녕'})
    assert not bridge.translation_settings()['data']['verified']
    assert bridge.test_translation_connection()['ok']
    assert not bridge.translation_settings()['data']['verified']
    assert bridge.jobs.fn(lambda *args: None) == {'verified':True}
    assert bridge.translation_settings()['data']['verified']
    assert bridge.save_translation_settings('google')['data']['verified']
    assert not bridge.save_translation_settings('deepl-free')['data']['verified']

def test_failure_invalidates_old_success(bridge, monkeypatch):
    bridge.registry.settings['verified'] = True
    def fail(*args): raise ValueError('ui.translation.authentication')
    monkeypatch.setattr(module.DescriptionTranslator, 'translate', fail)
    bridge.test_translation_connection()
    with pytest.raises(ValueError): bridge.jobs.fn(lambda *args: None)
    assert not bridge.translation_settings()['data']['verified']

def test_changed_configuration_cannot_receive_old_success(bridge, monkeypatch):
    def translate(*args): bridge.registry.settings['mode']='deepl-pro'
    monkeypatch.setattr(module.DescriptionTranslator, 'translate', translate)
    bridge.test_translation_connection()
    with pytest.raises(ValueError, match='stale'): bridge.jobs.fn(lambda *args: None)
    assert not bridge.translation_settings()['data']['verified']

def test_unverified_translation_is_blocked(bridge):
    assert not bridge.start_translate_description('Text', 'ko')['ok']


def test_new_key_invalidates_even_when_secret_reference_is_reused(bridge, monkeypatch):
    bridge.registry.settings['verified']=True
    monkeypatch.setattr(module.secrets, 'store', lambda *args: 'reference')
    assert not bridge.save_translation_settings('google', 'new-key')['data']['verified']


def test_late_test_cannot_overwrite_a_newer_test(bridge, monkeypatch):
    monkeypatch.setattr(module.DescriptionTranslator, 'translate', lambda *args: None)
    bridge.test_translation_connection(); old = bridge.jobs.fn
    bridge.test_translation_connection()
    with pytest.raises(ValueError, match='stale'): old(lambda *args: None)
    assert not bridge.translation_settings()['data']['verified']
