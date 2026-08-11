from vision_augment.envelope import (
    ERROR_CODES,
    ChannelFailedError,
    ChannelTimeoutError,
    DependencyMissingError,
    InternalError,
    InvalidInputError,
    err,
    ok,
)


def test_ok_shape():
    body = ok("reasoning", "vision:fake@x", "a cat", 0.9, {"a": 1})
    assert body["code"] == 0
    assert body["error"] is None
    assert body["task_type"] == "reasoning"
    assert body["tool_used"] == "vision:fake@x"
    assert body["result"] == "a cat"
    assert body["confidence"] == 0.9
    assert body["metadata"] == {"a": 1}


def test_err_shape():
    body = err("ocr", InvalidInputError("bad input"))
    assert body["code"] == 3
    assert body["error"] == "bad input"
    assert body["result"] is None
    assert body["confidence"] == 0.0
    assert body["metadata"]["error_type"] == "invalid_input"


def test_error_code_mapping_is_complete():
    assert sorted(ERROR_CODES) == [0, 1, 2, 3, 4, 5]
    assert ERROR_CODES[0] == "success"
    assert ERROR_CODES[5] == "internal_error"


def test_error_classes_carry_expected_codes():
    assert ChannelFailedError("x").code == 1
    assert ChannelTimeoutError("x").code == 2
    assert InvalidInputError("x").code == 3
    assert DependencyMissingError("x").code == 4
    assert InternalError("x").code == 5
