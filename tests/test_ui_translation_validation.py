import json
from pathlib import Path

import pytest

from tools.validate_ui_translations import validate_catalog


def catalog(tmp_path, messages, caller=''):
    gui = tmp_path / 'gui_web'
    gui.mkdir()
    (gui / 'i18n-messages.js').write_text('window.RMSI18n.addMessages(' + json.dumps(messages) + ');', encoding='utf-8')
    (gui / 'app.js').write_text(caller, encoding='utf-8')
    return tmp_path


def test_current_catalog_has_required_translations():
    assert validate_catalog() > 100


def test_missing_english_fails(tmp_path):
    with pytest.raises(ValueError, match='missing required'):
        validate_catalog(catalog(tmp_path, {'ui.test':{'ko':'테스트'}}))


def test_parameter_drift_fails(tmp_path):
    with pytest.raises(ValueError, match='parameter names differ'):
        validate_catalog(catalog(tmp_path, {'ui.test':{'ko':'{count}개', 'en':'{number} items'}}))


def test_unknown_message_reference_fails(tmp_path):
    with pytest.raises(ValueError, match='unknown message'):
        validate_catalog(catalog(tmp_path, {}, 'msg("ui.unknown")'))


def test_matching_parameters_pass(tmp_path):
    assert validate_catalog(catalog(tmp_path, {'ui.test':{'ko':'{count}개', 'en':'{count} items'}}, 'msg("ui.test", {count:3})')) == 1

def test_optional_translation_parameter_drift_fails(tmp_path):
    with pytest.raises(ValueError, match=r'parameter names differ \(ja\)'):
        validate_catalog(catalog(tmp_path, {'ui.test':{'ko':'{count}개', 'en':'{count} items', 'ja':'{number}件'}}))

def test_scraper_settings_and_error_ids_have_all_supported_translations():
    source = Path('gui_web/i18n-messages.js').read_text(encoding='utf-8')
    start = source.index('{', source.index('addMessages('))
    messages, _ = json.JSONDecoder().raw_decode(source[start:])
    for key, forms in messages.items():
        if key.startswith(('ui.scrape.', 'ui.scraper.', 'ui.settings.', 'ui.dat.', 'ui.error.', 'ui.backup.', 'ui.core.', 'ui.metadata.')):
            for language in ('ja', 'es', 'fr'):
                assert forms.get(language), f'{key}: missing {language}'

def test_all_stable_ids_have_five_languages():
    assert validate_catalog(required_languages=('ko','en','ja','es','fr')) > 200


def test_missing_required_optional_language_fails(tmp_path):
    with pytest.raises(ValueError, match='missing required ko/en/ja'):
        validate_catalog(catalog(tmp_path, {'ui.test':{'ko':'확인','en':'OK'}}), required_languages=('ko','en','ja'))
