import warnings
from collections import namedtuple

import numpy as np
from fuzzywuzzy import process as fw_process
from scipy.linalg import ldl
from scipy.linalg import qr


def chol_params_to_lower_triangular_matrix(params):
    dim = number_of_triangular_elements_to_dimension(len(params))
    mat = np.zeros((dim, dim))
    mat[np.tril_indices(dim)] = params
    return mat


def cov_params_to_matrix(cov_params):
    """Build covariance matrix from 1d array with its lower triangular elements.

    Args:
        cov_params (np.array): 1d array with the lower triangular elements of a
            covariance matrix (in C-order)

    Returns:
        cov (np.array): a covariance matrix

    """
    lower = chol_params_to_lower_triangular_matrix(cov_params)
    cov = lower + np.tril(lower, k=-1).T
    return cov


def cov_matrix_to_params(cov):
    return cov[np.tril_indices(len(cov))]


def sdcorr_params_to_sds_and_corr(sdcorr_params):
    dim = number_of_triangular_elements_to_dimension(len(sdcorr_params))
    sds = np.array(sdcorr_params[:dim])
    corr = np.eye(dim)
    corr[np.tril_indices(dim, k=-1)] = sdcorr_params[dim:]
    corr += np.tril(corr, k=-1).T
    return sds, corr


def sds_and_corr_to_cov(sds, corr):
    diag = np.diag(sds)
    return diag @ corr @ diag


def cov_to_sds_and_corr(cov):
    sds = np.sqrt(np.diagonal(cov))
    diag = np.diag(1 / sds)
    corr = diag @ cov @ diag
    return sds, corr


def sdcorr_params_to_matrix(sdcorr_params):
    """Build covariance matrix out of variances and correlations.

    Args:
        sdcorr_params (np.array): 1d array with parameters. The dimensions of the
            covariance matrix are inferred automatically. The first dim parameters
            are assumed to be the variances. The remainder are the lower triangular
            elements (excluding the diagonal) of a correlation matrix.

    Returns:
        cov (np.array): a covariance matrix

    """
    return sds_and_corr_to_cov(*sdcorr_params_to_sds_and_corr(sdcorr_params))


def cov_matrix_to_sdcorr_params(cov):
    dim = len(cov)
    sds, corr = cov_to_sds_and_corr(cov)
    correlations = corr[np.tril_indices(dim, k=-1)]
    return np.hstack([sds, correlations])


def number_of_triangular_elements_to_dimension(num):
    """Calculate the dimension of a square matrix from number of triangular elements.

    Args:
        num (int): The number of upper or lower triangular elements in the matrix.

    Examples:
        >>> number_of_triangular_elements_to_dimension(6)
        3
        >>> number_of_triangular_elements_to_dimension(10)
        4

    """
    return int(np.sqrt(8 * num + 1) / 2 - 0.5)


def dimension_to_number_of_triangular_elements(dim):
    """Calculate number of triangular elements from the dimension of a square matrix.

    Args:
        dim (int): Dimension of a square matrix.

    """
    return int(dim * (dim + 1) / 2)


def index_element_to_string(element, separator="_"):
    if isinstance(element, (tuple, list)):
        as_strings = [str(entry) for entry in element]
        res_string = separator.join(as_strings)
    else:
        res_string = str(element)
    return res_string


def propose_algorithms(requested_algo, algos, number=3):
    """Propose a a number of algorithms based on similarity to the requested algorithm.

    Args:
        requested_algo (str): From the user requested algorithm.
        algos (dict(str, list(str))): Dictionary where keys are the package and values
            are lists of algorithms.
        number (int) : Number of proposals.

    Returns:
        proposals (list(str)): List of proposed algorithms.

    Example:
        >>> algos = {"scipy": ["L-BFGS-B", "TNC"], "nlopt": ["lbfgsb"]}
        >>> propose_algorithms("scipy_L-BFGS-B", algos, number=1)
        ['scipy_L-BFGS-B']
        >>> propose_algorithms("L-BFGS-B", algos, number=2)
        ['scipy_L-BFGS-B', 'nlopt_lbfgsb']

    """
    possibilities = [
        "_".join([origin, algo_name]) for origin in algos for algo_name in algos[origin]
    ]
    proposals_w_probs = fw_process.extract(requested_algo, possibilities, limit=number)
    proposals = [proposal[0] for proposal in proposals_w_probs]

    return proposals


def robust_cholesky(matrix, threshold=None, warn=True, return_info=False):
    """Lower triangular cholesky factor of *matrix*.

    Args:
        matrix (np.array): Square, symmetric and (almost) positive semi-definite matrix
        threshold (float): Small negative number. Diagonal elements of D from the LDL
            decomposition between threshold and zero are set to zero. Default is
            minus machine accuracy.
        warn (bool): If True, the user is warned about negative elements in D
        return_info (bool): If True, also return a dictionary with 'method' and
            'diagonals'. Method can take the values 'np.linalg.cholesky',
            'LDL cholesky' and 'LDL cholesky with QR decomposition'.
            'diagonals' are the diagonal entries of D. They can be used to construct
            penalty terms for non positive definite matrices. Note that diagonals will
            also be returned if the standard cholesky decomposition did not fail. This
            allows for smooth penalty terms that start before actually reaching invalid
            matrices.

    Returns:
        chol (np.array): Cholesky factor of matrix
        info (float, optional): see return_info.

    Raises:
        np.linalg.LinalgError if the diagonal entries of D from the LDL decomposition
        are smaller than threshold.

    In contrast to a regular cholesky decomposition, this function will also
    work for matrices that are only positive semi-definite or even indefinite.

    For speed and precision reasons we first try a regular cholesky decomposition.
    If it fails we switch to more robust methods. For this we first take an LDL
    decomposition and set diagonal elements in D that are negative but above
    threshold to 0. Then we use the modified D to construct a candidate cholesky
    factor. If the candidate is not lower triangular, we use a QR decomposition to
    make it lower triangular.


    """
    sum_stabilized = 0.0

    try:
        chol = np.linalg.cholesky(matrix)
        method = "np.linalg.cholesky"
        diags = np.diagonal(chol) ** 2
    except np.linalg.LinAlgError:
        method = "LDL cholesky"
        threshold = threshold if threshold is not None else -np.finfo(float).eps

        lu, d, _ = ldl(matrix)

        diags = np.diagonal(d).copy()

        for i in range(len(diags)):
            if diags[i] >= 0:
                diags[i] = np.sqrt(diags[i])
            elif diags[i] > threshold:
                diags[i] = 0
                sum_stabilized += diags[i]
            else:
                raise np.linalg.LinAlgError(
                    "Diagonal entry below threshold in D from LDL decomposition."
                )

        if sum_stabilized < 0 and warn:
            warnings.warn(
                "Negative diagonal entry has been set to 0 in robust_cholesky.",
                category=RuntimeWarning,
            )

        candidate = lu * diags.reshape(1, len(diags))

        is_triangular = (candidate[np.triu_indices(len(matrix), k=1)] == 0).all()

        if is_triangular:
            chol = candidate
            method = "LDL cholesky"
        else:
            _, r = qr(candidate.T)
            chol = r.T
            method = "LDL cholesky with QR decomposition"

    info = {"method": method, "diagonals": diags}

    res = (chol, info) if return_info else chol
    return res


def namedtuple_from_dict(field_dict):
    """Filled namedtuple generated from a dictionary.

    Example:
        >>> namedtuple_from_dict({'a': 1, 'b': 2})
        NamedTuple(a=1, b=2)

    """
    return namedtuple("NamedTuple", field_dict)(**field_dict)


def namedtuple_from_kwargs(**kwargs):
    """Filled namedtuple generated from keyword arguments.

    Example:
        >>> namedtuple_from_kwargs(a=1, b=2)
        NamedTuple(a=1, b=2)

    """
    return namedtuple("NamedTuple", kwargs)(**kwargs)


def namedtuple_from_iterables(field_names, field_entries):
    """Filled namedtuple generated from field_names and field_entries.

    Example:
        >>> namedtuple_from_iterables(field_names=['a', 'b'], field_entries=[1, 2])
        NamedTuple(a=1, b=2)

    """
    return namedtuple("NamedTuple", field_names)(*field_entries)
