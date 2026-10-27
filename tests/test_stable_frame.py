import numpy as np

from scripts.stable_frame import choose_plateau, diff_series, plateau_runs


def test_diff_series_matches_between_consecutive_frames():
    vecs = [np.zeros((2, 2)), np.ones((2, 2)) * 2, np.ones((2, 2)) * 2]
    assert diff_series(vecs) == [2.0, 0.0]


def test_plateau_runs_finds_stable_window():
    diffs = [5.0, 0.1, 0.1, 9.0]
    assert plateau_runs(diffs, threshold=1.0) == [(1, 3)]


def test_choose_plateau_prefers_longest_low_diff_run():
    diffs = [8.0, 0.1, 0.1, 0.1, 9.0, 0.2, 0.2, 7.0]
    picked = choose_plateau(diffs, threshold=1.0)
    assert picked["plateau"]["length"] >= 4
    assert 2 <= picked["chosen_index"] <= 4


def test_choose_plateau_falls_back_when_everything_is_unstable():
    diffs = [9.0] * 5
    picked = choose_plateau(diffs, threshold=1.0)
    assert 0 <= picked["chosen_index"] <= len(diffs)
