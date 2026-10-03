"""Explicit description translation; cached originals are separate from game metadata."""
from __future__ import annotations
import hashlib
import html
import sqlite3
import time
from pathlib import Path
try:
    import requests
except ImportError:
    requests = None

LANGUAGES = {'ko': 'KO', 'en': 'EN-US', 'ja': 'JA', 'es': 'ES', 'fr': 'FR'}
MODES = {'off', 'deepl-free', 'deepl-pro', 'google'}

class TranslationError(ValueError):
    pass

class DescriptionTranslator:
    def __init__(self, database):
        self.database = Path(database)

    def _connect(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS translations (digest TEXT, language TEXT, provider TEXT, original TEXT, translated TEXT, source_language TEXT, created REAL, PRIMARY KEY(digest,language,provider))')
        db.execute('CREATE TABLE IF NOT EXISTS originals (game_key TEXT PRIMARY KEY, original TEXT, translated TEXT)')
        return db

    def translate(self, text, target_language, mode, api_key, progress=lambda *args: None):
        if not isinstance(text, str) or not text.strip():
            raise TranslationError('ui.translation.empty')
        if target_language not in LANGUAGES:
            raise TranslationError('ui.translation.languageInvalid')
        if mode not in MODES or mode == 'off' or not api_key:
            raise TranslationError('ui.translation.configure')
        if len(text.encode('utf-8')) > 64000:
            raise TranslationError('ui.translation.tooLong')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        progress(0, 1, 'ui.translation.working')
        with self._connect() as db:
            cached = db.execute('SELECT translated,source_language FROM translations WHERE digest=? AND language=? AND provider=?', (digest,target_language,mode)).fetchone()
        if cached:
            progress(1,1,'ui.translation.ready')
            return {'original':text,'translated':cached[0],'sourceLanguage':cached[1],'targetLanguage':target_language,'cached':True,'digest':digest,'provider':mode}
        if requests is None:
            raise TranslationError('ui.translation.dependency')
        try:
            if mode.startswith('deepl-'):
                endpoint = 'https://api-free.deepl.com/v2/translate' if mode == 'deepl-free' else 'https://api.deepl.com/v2/translate'
                response = requests.post(endpoint, headers={'Authorization':'DeepL-Auth-Key '+api_key}, json={'text':[text],'target_lang':LANGUAGES[target_language],'preserve_formatting':True}, timeout=(4,15))
            else:
                response = requests.post('https://translation.googleapis.com/language/translate/v2', headers={'X-Goog-Api-Key':api_key}, json={'q':text,'target':target_language,'format':'text'}, timeout=(4,15))
            with response:
                if response.status_code in (401,403): raise TranslationError('ui.translation.authentication')
                if response.status_code in (429,456): raise TranslationError('ui.translation.quota')
                if response.status_code != 200: raise TranslationError('ui.translation.serviceError')
                data = response.json()
            entry = data['translations'][0] if mode.startswith('deepl-') else data['data']['translations'][0]
            translated = entry['text'] if mode.startswith('deepl-') else html.unescape(entry['translatedText'])
            source = entry.get('detected_source_language',entry.get('detectedSourceLanguage',''))
            if not isinstance(translated,str) or not translated.strip(): raise TranslationError('ui.translation.serviceError')
        except requests.Timeout:
            raise TranslationError('ui.translation.timeout') from None
        except requests.RequestException:
            raise TranslationError('ui.translation.connection') from None
        except (KeyError,IndexError,TypeError,ValueError) as exc:
            if isinstance(exc,TranslationError): raise
            raise TranslationError('ui.translation.serviceError') from None
        # Cancellation is checked before cache writes and before the UI can use the result.
        progress(1,1,'ui.translation.ready')
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO translations VALUES (?,?,?,?,?,?,?)',(digest,target_language,mode,text,translated,str(source),time.time()))
            db.execute('DELETE FROM translations WHERE rowid IN (SELECT rowid FROM translations ORDER BY created DESC LIMIT -1 OFFSET 1000)')
        return {'original':text,'translated':translated,'sourceLanguage':str(source),'targetLanguage':target_language,'cached':False,'digest':digest,'provider':mode}

    def remember(self, game_key, result):
        with self._connect() as db:
            found = db.execute('SELECT original,translated FROM translations WHERE digest=? AND language=? AND provider=?',(result.get('digest'),result.get('targetLanguage'),result.get('provider'))).fetchone()
            if not found or found != (result.get('original'),result.get('translated')):
                raise TranslationError('ui.translation.stale')
            prior = db.execute('SELECT original,translated FROM originals WHERE game_key=?',(game_key,)).fetchone()
            original = prior[0] if prior and prior[1] == found[0] else found[0]
            db.execute('INSERT OR REPLACE INTO originals VALUES (?,?,?)',(game_key,original,found[1]))
        return True

    def original(self, game_key, text):
        with self._connect() as db:
            row=db.execute('SELECT original,translated FROM originals WHERE game_key=?',(game_key,)).fetchone()
        return row[0] if row and row[1] == text else None
