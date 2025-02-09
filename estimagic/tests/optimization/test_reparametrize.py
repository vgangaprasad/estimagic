from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pandas.testing import assert_series_equal

from estimagic.optimization.process_constraints import process_constraints
from estimagic.optimization.reparametrize import _increasing_to_internal
from estimagic.optimization.reparametrize import _probability_to_internal
from estimagic.optimization.reparametrize import _sum_to_internal
from estimagic.optimization.reparametrize import reparametrize_from_internal
from estimagic.optimization.reparametrize import reparametrize_to_internal

fix_path = Path(__file__).resolve().parent / "fixtures" / "reparametrize_fixtures.csv"
params_fixture = pd.read_csv(fix_path)
params_fixture.set_index(["category", "subcategory", "name"], inplace=True)
for col in ["lower", "internal_lower"]:
    params_fixture[col].fillna(-np.inf, inplace=True)
for col in ["upper", "internal_upper"]:
    params_fixture[col].fillna(np.inf, inplace=True)

external = []
internal = []

for i in range(3):
    ext = params_fixture.copy(deep=True)
    ext.rename(columns={"value{}".format(i): "value"}, inplace=True)
    external.append(ext)

    int_ = params_fixture.copy(deep=True)
    int_.rename(columns={"internal_value{}".format(i): "value"}, inplace=True)
    int_.dropna(subset=["value"], inplace=True)
    int_.drop(columns=["lower", "upper"], inplace=True)
    int_.rename(
        columns={"internal_lower": "lower", "internal_upper": "upper"}, inplace=True
    )
    internal.append(int_)


def constraints(params):
    constr = [
        {"loc": ("c", "c2"), "type": "probability"},
        {
            "loc": [("a", "a", "0"), ("a", "a", "2"), ("a", "a", "4")],
            "type": "fixed",
            "value": [0.1, 0.3, 0.5],
        },
        {"loc": ("e", "off"), "type": "fixed", "value": 0},
        {"loc": "d", "type": "increasing"},
        {"loc": "e", "type": "covariance"},
        {"loc": "f", "type": "covariance"},
        {"loc": "g", "type": "sum", "value": 5},
        {"loc": "h", "type": "equality"},
        {"loc": "i", "type": "equality"},
        {"query": 'subcategory == "j1" | subcategory == "i1"', "type": "equality"},
        {"loc": "k", "type": "sdcorr"},
        {"loc": "l", "type": "covariance"},
        {"locs": ["f", "l"], "type": "pairwise_equality"},
        {"loc": "m", "type": "covariance"},
        {"loc": ("m", "diag", "a"), "type": "fixed", "value": 4.0},
    ]
    constr = process_constraints(constr, params)
    return constr


internal_categories = list("abcdefghikm")
external_categories = internal_categories + ["j1", "j2", "l"]

to_test = []
for ext, int_ in zip(external, internal):
    for category in internal_categories:
        to_test.append((ext, int_, category))


@pytest.mark.parametrize("params, expected_internal, category", to_test)
def test_reparametrize_to_internal(params, expected_internal, category):
    constr = constraints(params)
    cols = ["value", "lower", "upper"]

    calculated = reparametrize_to_internal(params, constr, None)
    assert_frame_equal(
        calculated.loc[category, cols], expected_internal.loc[category, cols]
    )


to_test = []
for int_, ext in zip(internal, external):
    for category in external_categories:
        to_test.append((int_, ext, category))


@pytest.mark.parametrize("internal, expected_external, category", to_test)
def test_reparametrize_from_internal(internal, expected_external, category):
    constr = constraints(expected_external)

    calculated = reparametrize_from_internal(internal, constr, expected_external, None)[
        "value"
    ]
    assert_series_equal(calculated[category], expected_external.loc[category, "value"])


def test_invalid_sum():
    df = pd.DataFrame(data=[[1], [2], [2.9]], columns=["value"])
    df["lower"] = np.nan
    df["upper"] = np.nan
    df["_fixed"] = False
    with pytest.raises(AssertionError):
        _sum_to_internal(df, 6)


def test_invalid_probability():
    df = pd.DataFrame(data=[[0.1], [0.2], [0.72]], columns=["value"])
    df["lower"] = np.nan
    df["upper"] = np.nan
    df["_fixed"] = False
    with pytest.raises(AssertionError):
        _probability_to_internal(df)


def test_invalid_bound_for_increasing():
    df = pd.DataFrame(data=[[1], [2], [2.9]], columns=["value"])
    df["lower"] = [-np.inf, 1, -np.inf]
    df["upper"] = np.nan
    df["_fixed"] = False
    with pytest.warns(UserWarning):
        _increasing_to_internal(df)


def test_only_first_bounded_incresing():
    df = pd.DataFrame(data=[[1], [2], [2.9]], columns=["value"])
    df["lower"] = [1, -np.inf, -np.inf]
    df["upper"] = np.nan
    df["_fixed"] = False
    calculated = _increasing_to_internal(df)
    expected = calculated.copy(deep=True)
    expected["lower"] = [1.0, 0, 0]
    expected["value"] = [1, 1, 0.9]
    pd.testing.assert_frame_equal(
        calculated[["value", "lower"]], expected[["value", "lower"]]
    )


def test_all_bounds_same_increasing():
    df = pd.DataFrame(data=[[1], [2], [2.9]], columns=["value"])
    df["lower"] = [1.0, 1, 1]
    df["upper"] = np.nan
    df["_fixed"] = False
    calculated = _increasing_to_internal(df)
    expected = calculated.copy(deep=True)
    expected["lower"] = [1.0, 0, 0]
    expected["value"] = [1, 1, 0.9]
    pd.testing.assert_frame_equal(
        calculated[["value", "lower"]], expected[["value", "lower"]]
    )
