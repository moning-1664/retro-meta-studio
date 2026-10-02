"""Required five-language catalog and rendered-screen checks. No packaging side effects."""
import argparse
import functools
import http.server
import json
import re
import shutil
import subprocess
import threading
try:
    from .ui_translation_sources import backend_messages
except ImportError:
    from ui_translation_sources import backend_messages
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_catalog(root=ROOT, required_languages=('ko', 'en')):
    source = (root / 'gui_web/i18n-messages.js').read_text(encoding='utf-8')
    start = source.index('{', source.index('addMessages('))
    messages, _ = json.JSONDecoder().raw_decode(source[start:])
    errors = []
    for key, forms in messages.items():
        if not key.startswith('ui.') or any(not forms.get(language) for language in required_languages):
            errors.append(f'{key}: missing required {"/".join(required_languages)} translation')
        parameters = set(re.findall(r'\{(\w+)\}', forms.get('ko','')))
        for language in ('en', 'ja', 'es', 'fr'):
            if language in forms and parameters != set(re.findall(r'\{(\w+)\}', forms[language])):
                errors.append(f'{key}: parameter names differ ({language})')
    if 'addBackendMessages(' in source:
        rule_start = source.index('[', source.index('addBackendMessages('))
        rules, _ = json.JSONDecoder().raw_decode(source[rule_start:])
        for rule in rules:
            key = rule['key']
            if key not in messages:
                errors.append(f'backend rule: unknown message {key}')
                continue
            expected = set(re.findall(r'\{(\w+)\}', rule['template']))
            if rule.get('prefix'):
                expected.discard('detail')
            actual = set(re.findall(r'\{(\w+)\}', messages[key]['ko']))
            if expected != actual:
                errors.append(f'{key}: backend rule parameter names differ')
    for file in (root / 'gui_web').glob('*.js'):
        if file.name == 'i18n-messages.js':
            continue
        for key in re.findall(r'["\'](ui\.[\w.]+)["\']', file.read_text(encoding='utf-8')):
            if key not in messages:
                errors.append(f'{file.name}: unknown message {key}')
    if errors:
        raise ValueError('\n'.join(errors))
    return len(messages)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog-only', action='store_true')
    args = parser.parse_args()
    print(f'Validated {validate_catalog(required_languages=("ko","en","ja","es","fr"))} message IDs in five languages.')
    if args.catalog_only:
        return 0
    node = shutil.which('node')
    cli = ROOT / 'node_modules/@playwright/test/cli.js'
    if not node or not cli.exists():
        raise RuntimeError('UI translation validation requires Node.js, npm ci, and npx playwright install chromium.')

    source_audit = subprocess.run([node, str(ROOT / 'tools/audit_ui_translations.cjs')],
                                  cwd=ROOT, input=json.dumps(backend_messages(ROOT), ensure_ascii=False),
                                  encoding='utf-8')
    if source_audit.returncode:
        return source_audit.returncode

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(ROOT / 'gui_web'))
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        import os
        env = {**os.environ, 'RMS_I18N_BASE_URL':f'http://127.0.0.1:{server.server_port}'}
        try:
            return subprocess.run([node, str(cli), 'test', '--config=playwright.i18n.config.js', '--workers=2'], cwd=ROOT, env=env).returncode
        finally:
            server.shutdown()
            thread.join()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as error:
        print(f'Translation validation failed: {error}')
        raise SystemExit(1)
