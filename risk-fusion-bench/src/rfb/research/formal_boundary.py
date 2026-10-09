class ResearchNotPromotable(ValueError):
    pass


def reject_research_receipt(receipt):
    raise ResearchNotPromotable("research receipt is non-promotable")


def assert_shk001b_blocked(receipt):
    raise ResearchNotPromotable("SHK-001B blocked without formal admission")
