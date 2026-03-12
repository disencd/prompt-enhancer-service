"""Tests for the error pattern detection engine."""

from prompt_pulse.terminal.error_patterns import ErrorDetectionEngine


def test_typescript_error():
    engine = ErrorDetectionEngine()
    text = "src/auth/middleware.ts(42,5): error TS2345: Argument of type 'string' is not assignable to parameter of type 'AuthToken'."
    errors = engine.detect(text)
    assert len(errors) >= 1
    ts_err = [e for e in errors if e.error_type == "typescript_compilation"]
    assert len(ts_err) == 1
    assert ts_err[0].code == "TS2345"
    assert ts_err[0].file == "src/auth/middleware.ts"
    assert ts_err[0].line == 42


def test_python_traceback():
    engine = ErrorDetectionEngine()
    text = """Traceback (most recent call last):
  File "/app/server.py", line 87, in handle_request
    result = process(data)
  File "/app/utils.py", line 12, in process
    return data["key"]
KeyError: 'key'
"""
    errors = engine.detect(text)
    files = [e for e in errors if e.error_type == "python_traceback"]
    assert len(files) >= 2
    assert files[0].file == "/app/server.py"
    assert files[0].line == 87


def test_python_exception():
    engine = ErrorDetectionEngine()
    text = "ValueError: invalid literal for int() with base 10: 'abc'"
    errors = engine.detect(text)
    exc = [e for e in errors if e.error_type == "python_exception"]
    assert len(exc) == 1
    assert exc[0].code == "ValueError"


def test_go_error():
    engine = ErrorDetectionEngine()
    text = "./main.go:15:2: undefined: fmt.Printlnn"
    errors = engine.detect(text)
    go_err = [e for e in errors if e.error_type == "go_compilation"]
    assert len(go_err) == 1
    assert go_err[0].file == "./main.go"
    assert go_err[0].line == 15


def test_permission_error():
    engine = ErrorDetectionEngine()
    text = "EACCES: permission denied, open '/etc/shadow'"
    errors = engine.detect(text)
    perm = [e for e in errors if e.error_type == "permission_error"]
    assert len(perm) >= 1


def test_generic_error():
    engine = ErrorDetectionEngine()
    text = "fatal: not a git repository"
    errors = engine.detect(text)
    gen = [e for e in errors if e.error_type == "generic"]
    assert len(gen) >= 1


def test_no_errors():
    engine = ErrorDetectionEngine()
    text = "Build succeeded.\n3 tests passed."
    errors = engine.detect(text)
    assert len(errors) == 0


def test_dedup_errors():
    engine = ErrorDetectionEngine()
    text = "src/app.ts(10,1): error TS1005: ';' expected.\nsrc/app.ts(10,1): error TS1005: ';' expected."
    errors = engine.detect(text)
    ts_errors = [e for e in errors if e.error_type == "typescript_compilation"]
    # Should be deduped to 1
    assert len(ts_errors) == 1


def test_jest_failure():
    engine = ErrorDetectionEngine()
    text = """  ● Auth module > should validate tokens

    expect(received).toBe(expected)"""
    errors = engine.detect(text)
    jest = [e for e in errors if e.error_type == "jest_test_failure"]
    assert len(jest) == 1


def test_pytest_failure():
    engine = ErrorDetectionEngine()
    text = "FAILED tests/test_auth.py::test_login_invalid"
    errors = engine.detect(text)
    pytest_err = [e for e in errors if e.error_type == "pytest_failure"]
    assert len(pytest_err) == 1
    assert pytest_err[0].file == "tests/test_auth.py"
