from __future__ import annotations


GAS_CONSTANT_J_MOL_K = 8.314462618

FORMATION_ENERGY_THRESHOLD_EV_ATOM = 0.05
DELTA_THRESHOLD_PERCENT = 6.6
OMEGA_THRESHOLD = 1.1


ATOMIC_RADIUS_ANG = {
    "Al": 1.43, "Co": 1.25, "Cr": 1.28,
    "Cu": 1.28, "Fe": 1.26, "Ga": 1.35,
    "Ge": 1.22, "Mn": 1.39, "Mo": 1.39,
    "Ni": 1.25, "Ti": 1.47, "Zn": 1.33,
    "Ag": 1.44, "Pd": 1.37, "Pt": 1.39,
    "Au": 1.44,
}


MELTING_POINT_K = {
    "Al": 933.47, "Co": 1768.0, "Cr": 2180.0,
    "Cu": 1357.77, "Fe": 1811.0, "Ga": 302.91,
    "Ge": 1211.4, "Mn": 1519.0, "Mo": 2896.0,
    "Ni": 1728.0, "Ti": 1941.0, "Zn": 692.68,
    "Ag": 1234.93, "Pd": 1828.05,
    "Pt": 2041.4, "Au": 1337.33,
}


_RAW_H_MIX_KJMOL = {
    ("Al", "Co"): -19, ("Al", "Cr"): -10,
    ("Al", "Cu"): -1, ("Al", "Fe"): -11,
    ("Al", "Ga"): 0, ("Al", "Ge"): -20,
    ("Al", "Mn"): -19, ("Al", "Mo"): -22,
    ("Al", "Ni"): -22, ("Al", "Ti"): -30,
    ("Al", "Zn"): -1,

    ("Co", "Cr"): 0, ("Co", "Cu"): 6,
    ("Co", "Fe"): 0, ("Co", "Ga"): 0,
    ("Co", "Ge"): -10, ("Co", "Mn"): 0,
    ("Co", "Mo"): -7, ("Co", "Ni"): -4,
    ("Co", "Ti"): -24, ("Co", "Zn"): 0,

    ("Cr", "Cu"): 12, ("Cr", "Fe"): 1,
    ("Cr", "Ga"): 0, ("Cr", "Ge"): -6,
    ("Cr", "Mn"): 0, ("Cr", "Mo"): 0,
    ("Cr", "Ni"): 4, ("Cr", "Ti"): -7,
    ("Cr", "Zn"): 0,

    ("Cu", "Fe"): 13, ("Cu", "Ga"): 4,
    ("Cu", "Ge"): -1, ("Cu", "Mn"): 4,
    ("Cu", "Mo"): -4, ("Cu", "Ni"): -4,
    ("Cu", "Ti"): -9, ("Cu", "Zn"): 4,

    ("Fe", "Ga"): 0, ("Fe", "Ge"): -17,
    ("Fe", "Mn"): 0, ("Fe", "Mo"): -2,
    ("Fe", "Ni"): -2, ("Fe", "Ti"): -17,
    ("Fe", "Zn"): 0,

    ("Ga", "Ge"): -4, ("Ga", "Mn"): 0,
    ("Ga", "Mo"): 0, ("Ga", "Ni"): 0,
    ("Ga", "Ti"): -10, ("Ga", "Zn"): 0,

    ("Ge", "Mn"): 0, ("Ge", "Mo"): 0,
    ("Ge", "Ni"): -4, ("Ge", "Ti"): -15,
    ("Ge", "Zn"): 0,

    ("Mn", "Mo"): -1, ("Mn", "Ni"): -4,
    ("Mn", "Ti"): -8, ("Mn", "Zn"): 0,

    ("Mo", "Ni"): -7, ("Mo", "Ti"): -16,
    ("Mo", "Zn"): 0,

    ("Ni", "Ti"): -35, ("Ni", "Zn"): 4,
    ("Ti", "Zn"): -2,

    ("Ag", "Al"): -8, ("Ag", "Co"): -23,
    ("Ag", "Cr"): -28, ("Ag", "Cu"): -6,
    ("Ag", "Fe"): -23, ("Ag", "Ga"): -8,
    ("Ag", "Ge"): -14.5, ("Ag", "Mn"): -34,
    ("Ag", "Mo"): -28, ("Ag", "Ni"): -23,
    ("Ag", "Ti"): -54, ("Ag", "Zn"): -8,

    ("Al", "Pd"): -46, ("Co", "Pd"): -1,
    ("Cr", "Pd"): 15, ("Cu", "Pd"): -33,
    ("Fe", "Pd"): 28, ("Ga", "Pd"): -5,
    ("Ge", "Pd"): -17.5, ("Mn", "Pd"): -23,
    ("Mo", "Pd"): -15, ("Ni", "Pd"): -14,
    ("Pd", "Ti"): -65, ("Pd", "Zn"): -4,

    ("Al", "Pt"): -44, ("Co", "Pt"): -3,
    ("Cr", "Pt"): 24, ("Cu", "Pt"): -5,
    ("Fe", "Pt"): -13, ("Ga", "Pt"): -12,
    ("Ge", "Pt"): -38, ("Mn", "Pt"): -28,
    ("Mo", "Pt"): -28, ("Ni", "Pt"): -7,
    ("Pt", "Ti"): -74, ("Pt", "Zn"): -12,

    ("Al", "Au"): -44, ("Au", "Co"): 8,
    ("Au", "Cr"): -19, ("Au", "Cu"): 5,
    ("Au", "Fe"): -11, ("Au", "Ga"): -29,
    ("Au", "Ge"): -38, ("Au", "Mn"): 0,
    ("Au", "Mo"): -28, ("Au", "Ni"): 7,
    ("Au", "Ti"): -47, ("Au", "Zn"): -12,

    ("Ag", "Au"): -6, ("Ag", "Pd"): 0,
    ("Ag", "Pt"): -6, ("Au", "Pd"): 0,
    ("Au", "Pt"): 0, ("Pd", "Pt"): 0,
}


def canonical_pair(
    first: str,
    second: str,
) -> tuple[str, str]:
    return tuple(sorted((first, second)))


H_MIX_KJMOL = {
    canonical_pair(first, second): value
    for (first, second), value
    in _RAW_H_MIX_KJMOL.items()
}


SUPPORTED_STABILITY_ELEMENTS = frozenset(
    ATOMIC_RADIUS_ANG
)