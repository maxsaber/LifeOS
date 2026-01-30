# Archived Test Files

Test files in this directory have been superseded by newer, more comprehensive tests.

**Archived**: 2026-01-30

## Archived Files

### test_chunking.py
- **Superseded by**: `tests/test_chunker.py`
- **Reason**: test_chunker.py has 47 tests vs 25 tests in the old file
- **Coverage**: All functionality from test_chunking.py is covered in test_chunker.py

### test_conversations.py
- **Superseded by**: `tests/test_conversation_store.py` + `tests/test_conversations_api.py`
- **Reason**: The new files have 54 + 23 = 77 tests vs 27 tests in the old file
- **Coverage**: Store tests in test_conversation_store.py, API tests in test_conversations_api.py

## Recovery

If any test is needed again, move it back to `tests/`:
```bash
mv tests/archive/test_name.py tests/
```
