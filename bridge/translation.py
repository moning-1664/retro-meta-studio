"""Translation jobs do not mutate Collection or Archive metadata."""
import json
import uuid
from pathlib import Path
from app.description_translation import DescriptionTranslator, MODES
from app.scrape import secrets
from bridge.responses import guarded, ok

class TranslationBridge:
    def _description_translator(self):
        return DescriptionTranslator(self._scrape_cache_dir.parent / 'translation_cache.db')

    @guarded
    def translation_settings(self):
        settings = self.registry.get_setting('descriptionTranslation',{}) or {}
        return ok({'mode':settings.get('mode','off'),'hasKey':bool(settings.get('key')), 'verified':bool(settings.get('verified') and settings.get('key') and settings.get('mode') != 'off')})

    @guarded
    def save_translation_settings(self, mode, api_key=None):
        if mode not in MODES: raise ValueError('ui.translation.configure')
        old=self.registry.get_setting('descriptionTranslation',{}) or {}
        reference=old.get('key','') if old.get('mode')==mode else ''
        if api_key is not None:
            if not isinstance(api_key,str): raise ValueError('ui.translation.configure')
            reference=secrets.store('descriptionTranslation',api_key.strip()) if api_key.strip() else ''
        changed = api_key is not None or old.get('mode') != mode
        self.registry.set_setting('descriptionTranslation',{'mode':mode,'key':reference,
            'revision':uuid.uuid4().hex if changed else old.get('revision'),
            'verified':bool(not changed and old.get('verified') and old.get('key')==reference)})
        if old.get('key') and old['key'] != reference: secrets.delete(old['key'])
        return self.translation_settings()

    @guarded
    def test_translation_connection(self):
        settings = self.registry.get_setting('descriptionTranslation', {}) or {}
        mode, reference = settings.get('mode', 'off'), settings.get('key')
        if mode == 'off' or not reference:
            raise ValueError('ui.translation.configure')
        token = uuid.uuid4().hex
        self.registry.set_setting('descriptionTranslation', {**settings, 'verified': False, 'testToken':token})
        key = secrets.load(reference)
        def run(progress):
            # A short real translation probes permission and quota; bypass the result cache.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='rms_translation_test_') as directory:
                DescriptionTranslator(Path(directory) / 'test.db').translate('Hello.', 'ko', mode, key, progress)
            current = self.registry.get_setting('descriptionTranslation', {}) or {}
            if (current.get('mode') != mode or current.get('key') != reference
                    or current.get('revision') != settings.get('revision') or current.get('testToken') != token):
                raise ValueError('ui.translation.stale')
            self.registry.set_setting('descriptionTranslation', {**current, 'verified': True})
            return {'verified': True}
        return ok({'jobId': self.jobs.run(run)})

    @guarded
    def start_translate_description(self, text, target_language):
        settings=self.registry.get_setting('descriptionTranslation',{}) or {}
        if settings.get('mode','off')=='off' or not settings.get('key') or not settings.get('verified'):
            raise ValueError('ui.translation.configure')
        key=secrets.load(settings['key'])
        translator=self._description_translator()
        job=self.jobs.run(lambda progress:translator.translate(text,target_language,settings['mode'],key,progress))
        return ok({'jobId':job})

    def _translation_game_key(self, game_key):
        parts = json.loads(game_key)
        if not isinstance(parts,list) or len(parts)!=2 or not all(isinstance(value,str) and value for value in parts):
            raise ValueError('ui.translation.stale')
        if parts[0]=='archive':
            parts[0] = 'archive:' + self._archive_config().get('archiveDir','')
        return json.dumps(parts,ensure_ascii=False)

    @guarded
    def remember_description_translation(self, game_key, result):
        if not isinstance(game_key,str) or not game_key: raise ValueError('ui.translation.stale')
        return ok(self._description_translator().remember(self._translation_game_key(game_key),result))

    @guarded
    def original_description(self, game_key, text):
        return ok(self._description_translator().original(self._translation_game_key(game_key),text))
