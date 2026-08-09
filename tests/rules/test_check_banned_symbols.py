# OpenHardware — tests for the nondeterministic-symbol checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

from tools.check_banned_symbols import find_banned


def test_rand_call_is_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("int x = rand();\n", encoding="utf-8")
    assert find_banned([path]) == [(path, 1, "rand")]


def test_time_call_is_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("t = time(NULL);\n", encoding="utf-8")
    assert find_banned([path]) == [(path, 1, "time")]


def test_srand_is_not_mistaken_for_rand(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("srand(1);\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_comments_are_not_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("// never call rand() here\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_non_source_files_are_skipped(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("rand()\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_clean_file_passes(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("int x = cycles * 2;\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_call_after_same_line_block_comment_is_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("/* note */ x = rand();\n", encoding="utf-8")
    assert find_banned([path]) == [(path, 1, "rand")]


def test_call_inside_multiline_block_comment_is_not_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("/*\nrand();\n*/\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_trailing_comment_mentioning_banned_symbol_is_not_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text(
        "int x = cycles * 2; // comment mentioning rand()\n", encoding="utf-8"
    )
    assert find_banned([path]) == []


def test_call_after_multiline_block_comment_closes_is_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("/* still open\n*/ x = rand();\n", encoding="utf-8")
    assert find_banned([path]) == [(path, 2, "rand")]
