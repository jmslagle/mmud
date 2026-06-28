from mmud.tui._textual_patches import patch_textual_input_decoder


def test_input_decoder_tolerates_invalid_utf8_bytes():
    # Under screen/tmux a stray byte like 0x80 reaches Textual's stdin decoder; strict
    # UTF-8 crashed the input thread. After the patch it must decode tolerantly (U+FFFD).
    patch_textual_input_decoder()
    patch_textual_input_decoder()   # idempotent
    from textual.drivers import linux_driver
    decode = linux_driver.getincrementaldecoder("utf-8")().decode
    # the exact crash byte from the report — must NOT raise
    out = decode(b"abc\x80def", True)
    assert "�" in out and out.startswith("abc") and out.endswith("def")
