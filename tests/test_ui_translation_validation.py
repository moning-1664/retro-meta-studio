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
