"""Translation jobs do not mutate Collection or Archive metadata."""
import json
from app.description_translation import DescriptionTranslator, MODES
from app.scrape import secrets
from bridge.responses import guarded, ok

class TranslationBridge:
    def _description_translator(self):
        return DescriptionTranslator(self._scrape_cache_dir.parent / 'translation_cache.db')

    @guarded
    def translation_settings(self):
        settings = self.registry.get_setting('descriptionTranslation',{}) or {}
        return ok({'mode':settings.get('mode','off'),'hasKey':bool(settings.get('key'))})

    @guarded
    def save_translation_settings(self, mode, api_key=None):
        if mode not in MODES: raise ValueError('ui.translation.configure')
        old=self.registry.get_setting('descriptionTranslation',{}) or {}
        reference=old.get('key','') if old.get('mode')==mode else ''
        if api_key is not None:
            if not isinstance(api_key,str): raise ValueError('ui.translation.configure')
            reference=secrets.store('descriptionTranslation',api_key.strip()) if api_key.strip() else ''
        self.registry.set_setting('descriptionTranslation',{'mode':mode,'key':reference})
        if old.get('key') and old['key'] != reference: secrets.delete(old['key'])
        return self.translation_settings()

    @guarded
    def start_translate_description(self, text, target_language):
        settings=self.registry.get_setting('descriptionTranslation',{}) or {}
        if settings.get('mode','off')=='off' or not settings.get('key'):
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
