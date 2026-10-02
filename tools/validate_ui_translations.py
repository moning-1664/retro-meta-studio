"""Required five-language catalog and rendered-screen checks. No packaging side effects."""
import argparse
import functools
import http.server
import json
import re
import shutil
import subprocess
import threading
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
