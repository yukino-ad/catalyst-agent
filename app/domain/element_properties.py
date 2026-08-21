from __future__ import annotations


DATA_VERSION = "c2-element-properties-v1"

SUPPORTED_ELEMENTS = (
    "Al", "Co", "Cr", "Cu", "Fe", "Ga", "Ge", "Mn",
    "Mo", "Ni", "Ti", "Zn", "Ag", "Pd", "Pt", "Au",
)


# 地壳丰度，单位 ppm。
# 第一版用于候选间的相对比较，不代表经济可采储量。
CRUSTAL_ABUNDANCE_PPM = {
    "Al": 82300.0,
    "Fe": 56300.0,
    "Ti": 5650.0,
    "Mn": 950.0,
    "Cr": 102.0,
    "Ni": 84.0,
    "Zn": 70.0,
    "Cu": 60.0,
    "Co": 25.0,
    "Ga": 19.0,
    "Ge": 1.5,
    "Mo": 1.2,
    "Ag": 0.075,
    "Pd": 0.015,
    "Pt": 0.005,
    "Au": 0.004,
}


# 成本可行性分数，越高表示成本压力越低。
# 这是固定版本的分类评分，不是实时市场报价。
PRICE_SCORE = {
    "Fe": 100.0,
    "Al": 95.0,
    "Mn": 90.0,
    "Zn": 85.0,
    "Cr": 80.0,
    "Cu": 75.0,
    "Ni": 70.0,
    "Ti": 65.0,
    "Mo": 55.0,
    "Co": 50.0,
    "Ga": 45.0,
    "Ge": 35.0,
    "Ag": 30.0,
    "Pd": 10.0,
    "Pt": 8.0,
    "Au": 5.0,
}


# 元素级安全可行性先验，越高表示预期风险越低。
# 不能替代具体金属盐、氧化物、粉尘和纳米颗粒的毒理评价。
SAFETY_SCORE = {
    "Fe": 95.0,
    "Ti": 95.0,
    "Al": 85.0,
    "Au": 85.0,
    "Mo": 80.0,
    "Ag": 75.0,
    "Zn": 70.0,
    "Ge": 65.0,
    "Cu": 65.0,
    "Ga": 60.0,
    "Pd": 60.0,
    "Pt": 60.0,
    "Mn": 55.0,
    "Ni": 40.0,
    "Co": 35.0,
    "Cr": 35.0,
}


# 熔点，单位 K。
# C2 只用它估计合成温区跨度，不参与 Omega 计算。
MELTING_POINT_K = {
    "Al": 933.47,
    "Co": 1768.0,
    "Cr": 2180.0,
    "Cu": 1357.77,
    "Fe": 1811.0,
    "Ga": 302.91,
    "Ge": 1211.4,
    "Mn": 1519.0,
    "Mo": 2896.0,
    "Ni": 1728.0,
    "Ti": 1941.0,
    "Zn": 692.68,
    "Ag": 1234.93,
    "Pd": 1828.05,
    "Pt": 2041.4,
    "Au": 1337.33,
}


# 单元素常规合金制备处理难度的可行性分数。
# 越高表示越容易纳入常规熔炼或合金化流程。
ELEMENT_HANDLING_SCORE = {
    "Fe": 95.0,
    "Cu": 90.0,
    "Ni": 85.0,
    "Ag": 85.0,
    "Au": 85.0,
    "Co": 80.0,
    "Pd": 80.0,
    "Cr": 75.0,
    "Mn": 75.0,
    "Pt": 75.0,
    "Ge": 70.0,
    "Al": 65.0,
    "Ti": 55.0,
    "Mo": 50.0,
    "Ga": 45.0,
    "Zn": 40.0,
}


# 特殊工艺风险惩罚。
# Zn、Ga 分别反映挥发和低熔点问题；
# Al、Ti 反映氧化敏感；Mo 反映极高熔点。
PROCESS_RISK_PENALTY = {
    "Al": 10.0,
    "Co": 0.0,
    "Cr": 0.0,
    "Cu": 0.0,
    "Fe": 0.0,
    "Ga": 20.0,
    "Ge": 0.0,
    "Mn": 0.0,
    "Mo": 10.0,
    "Ni": 0.0,
    "Ti": 12.0,
    "Zn": 25.0,
    "Ag": 0.0,
    "Pd": 0.0,
    "Pt": 0.0,
    "Au": 0.0,
}


DATA_SOURCES = {
    "abundance": {
        "name": "Royal Society of Chemistry Periodic Table",
        "url": "https://www.rsc.org/periodic-table",
        "status": "versioned_reference_data",
    },
    "supply_and_price": {
        "name": "USGS Mineral Commodity Summaries 2025",
        "url": (
            "https://pubs.usgs.gov/periodicals/"
            "mcs2025/mcs2025.pdf"
        ),
        "status": "category_score_not_live_price",
    },
    "hazard": {
        "name": "PubChem and NIOSH",
        "url": "https://pubchem.ncbi.nlm.nih.gov/",
        "status": "element_level_conservative_prior",
    },
    "synthesis": {
        "name": "Rule-based engineering estimate",
        "status": "requires_future_experimental_calibration",
    },
}