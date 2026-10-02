"""Extract UI-facing backend messages without changing backend protocol strings."""
import ast
import re
from pathlib import Path

# ROM language tags are metadata defaults, not application interface copy.
METADATA_TAGS = {'한국(KR)', '영어권(EN)', '일본(JP)', '유럽(EU)', '글로벌'}


def backend_messages(root: Path):
    messages = {}
    for directory in ('app', 'bridge'):
        for file in (root / directory).rglob('*.py'):
            tree = ast.parse(file.read_text(encoding='utf-8-sig'))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant):
                    if not isinstance(node.value, str) or isinstance(parents.get(node), ast.JoinedStr):
                        continue
                    text = node.value
                elif isinstance(node, ast.JoinedStr):
                    parts, index = [], 0
                    for value in node.values:
                        if isinstance(value, ast.Constant):
                            parts.append(value.value)
                        else:
                            parts.append('{value' + str(index) + '}')
                            index += 1
                    text = ''.join(parts)
                else:
                    continue
                if not re.search('[가-힣]', text) or text in METADATA_TAGS:
                    continue
                # SQL comments and matching expressions are code, never UI text.
                if text.lstrip().startswith('CREATE TABLE') or " GLOB '*[가-힣" in text:
                    continue
                parent = parents.get(node)
                if isinstance(parent, ast.Expr):  # docstring
                    continue
                call = parent
                while call and not isinstance(call, (ast.Call, ast.Dict, ast.Assign, ast.AnnAssign, ast.Raise)):
                    call = parents.get(call)
                if isinstance(call, ast.Call):
                    name = ast.unparse(call.func)
                    if name.startswith(('logger.', 'logging.', 'log.', '_log.')) or name == 'print':
                        continue
                    if name == 're.compile':
                        continue
                if text.startswith('\\s') and ('한글' in text or '번역' in text):
                    continue
                messages.setdefault(text, {'file': str(file.relative_to(root)), 'line': node.lineno, 'text': text})
    return list(messages.values())
