"""Opaque case order and scorer-only truth mapping pinned to the review plan."""


CASE_IDS_BY_ARM = {
    "A": "38e02496822f1a85849b6a39f698e50d",
    "B": "33fadeeedeed902bd0ab9dfae5420213",
    "C": "42474559127419126b713096e9f4d3ee",
    "D": "81050a121e028f59f1e6940d7c5eb477",
}
CASE_ID_ORDER = tuple(CASE_IDS_BY_ARM.values())
EXPECTED_TRACE_BY_CASE_ID = {
    CASE_IDS_BY_ARM["A"]: "I1_NO_INFO_CONTINUING",
    CASE_IDS_BY_ARM["B"]: "I2_NO_INFO_NEW",
    CASE_IDS_BY_ARM["C"]: "I2_NO_INFO_NEW",
    CASE_IDS_BY_ARM["D"]: "I2_NO_INFO_NEW",
}
